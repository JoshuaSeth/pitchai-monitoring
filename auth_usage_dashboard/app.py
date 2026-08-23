from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field

from .mobile_auth import (
    AppAttestRegistry,
    ChallengeStore,
    MobileAuthError,
    canonical_client_data,
)
from .mobile_projection import build_mobile_snapshot
from .service import CapacityService, StateSource
from .settings import DashboardSettings
from .source import BrokerStateSource


ROOT = Path(__file__).resolve().parent
_ALLOWED_IDENTITY_DOMAIN = "pitchai.net"
_MAX_EMAIL_LENGTH = 254


class MobileChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: Literal["attest", "capacity", "refresh"]
    key_id: str = Field(min_length=40, max_length=128)


class MobileAttestationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: str = Field(min_length=36, max_length=36)
    key_id: str = Field(min_length=40, max_length=128)
    attestation: str = Field(min_length=1, max_length=131_072)


class MobileAssertionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: str = Field(min_length=36, max_length=36)
    key_id: str = Field(min_length=40, max_length=128)
    assertion: str = Field(min_length=1, max_length=32_768)


def _normalize_pitchai_email(raw_email: str | None) -> str | None:
    if raw_email is None or raw_email != raw_email.strip() or len(raw_email) > _MAX_EMAIL_LENGTH:
        return None
    email = raw_email.lower()
    local_part, separator, domain = email.rpartition("@")
    if email.count("@") != 1 or separator != "@" or not local_part or domain != _ALLOWED_IDENTITY_DOMAIN:
        return None
    if any(ord(character) < 33 or ord(character) > 126 for character in email):
        return None
    return email


def create_app(
    settings: DashboardSettings | None = None,
    *,
    source: StateSource | None = None,
    service: CapacityService | None = None,
    mobile_registry: AppAttestRegistry | None = None,
    challenge_store: ChallengeStore | None = None,
) -> FastAPI:
    settings = settings or DashboardSettings.from_env()
    source = source or BrokerStateSource(
        data_dir=settings.broker_data_dir,
        broker_url=settings.broker_url,
        admin_token=settings.broker_admin_token,
        request_timeout_seconds=settings.request_timeout_seconds,
    )
    service = service or CapacityService(settings, source)
    if settings.mobile_enabled:
        mobile_registry = mobile_registry or AppAttestRegistry(
            path=settings.mobile_app_attest_registry_file,
            root_certificate_path=settings.mobile_app_attest_root_certificate,
            app_id=f"{settings.mobile_app_id_prefix}.{settings.mobile_bundle_id}",
            environment=settings.mobile_app_attest_environment,
            max_keys=settings.mobile_app_attest_max_keys,
            enrollment_enabled=settings.mobile_app_attest_enrollment_enabled,
        )
        challenge_store = challenge_store or ChallengeStore(
            ttl_seconds=settings.mobile_challenge_ttl_seconds,
            max_pending=settings.mobile_challenge_max_pending,
        )
    else:
        mobile_registry = None
        challenge_store = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.capacity_service = service
        await service.start()
        try:
            yield
        finally:
            await service.stop()

    app = FastAPI(
        title="PitchAI Codex Capacity",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.mobile_registry = mobile_registry
    app.state.mobile_challenge_store = challenge_store
    app.state.templates = Jinja2Templates(directory=str(ROOT / "templates"))
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; connect-src 'self'; font-src 'self'; "
            "form-action 'self'; frame-ancestors 'none'; img-src 'self' data:; object-src 'none'; "
            "script-src 'self'; style-src 'self'"
        )
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=()"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return response

    def require_operator(request: Request) -> str:
        if not settings.require_proxy_auth:
            return "local-development@pitchai.net"
        email = _normalize_pitchai_email(request.headers.get(settings.proxy_auth_header))
        if email is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="PitchAI Entra SSO identity required",
            )
        return email

    def require_mobile_services() -> tuple[AppAttestRegistry, ChallengeStore]:
        registry = app.state.mobile_registry
        challenges = app.state.mobile_challenge_store
        if not isinstance(registry, AppAttestRegistry) or not isinstance(
            challenges, ChallengeStore
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return registry, challenges

    def raise_mobile_error(error: MobileAuthError) -> None:
        if error.code in {"enrollment_closed", "key_limit"}:
            status_code = status.HTTP_403_FORBIDDEN
        elif error.code == "key_already_registered":
            status_code = status.HTTP_409_CONFLICT
        elif error.code == "challenge_capacity":
            status_code = status.HTTP_429_TOO_MANY_REQUESTS
        elif error.code.startswith("challenge_") or error.code.startswith(
            ("key_", "attestation_", "assertion_", "base64_", "cbor_")
        ):
            status_code = status.HTTP_401_UNAUTHORIZED
        else:
            status_code = status.HTTP_400_BAD_REQUEST
        raise HTTPException(
            status_code=status_code,
            detail={"code": error.code, "message": error.detail},
        ) from error

    def mobile_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
        return build_mobile_snapshot(
            snapshot,
            manual_refresh_min_interval_seconds=settings.manual_probe_min_interval_seconds,
            recommended_background_refresh_seconds=settings.mobile_background_refresh_seconds,
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return await service.health()

    @app.get("/robots.txt", response_class=Response)
    async def robots() -> Response:
        return Response("User-agent: *\nDisallow: /\n", media_type="text/plain")

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        actor = require_operator(request)
        return app.state.templates.TemplateResponse(
            request,
            "dashboard.html",
            {"title": "Codex Capacity", "actor": actor},
        )

    @app.get("/api/v1/capacity")
    async def capacity(request: Request) -> JSONResponse:
        require_operator(request)
        return JSONResponse(await service.snapshot())

    @app.post("/api/v1/refresh")
    async def refresh(
        request: Request,
        action: str | None = Header(default=None, alias="X-Auth-Usage-Action"),
    ) -> JSONResponse:
        require_operator(request)
        if action != "refresh":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="missing refresh action header")
        return JSONResponse(await service.request_manual_probe())

    @app.post("/api/v1/mobile/challenge")
    async def mobile_challenge(payload: MobileChallengeRequest) -> JSONResponse:
        registry, challenges = require_mobile_services()
        try:
            if payload.purpose == "attest":
                if registry.has_key(payload.key_id):
                    raise MobileAuthError(
                        "key_already_registered",
                        "This App Attest key is already registered",
                    )
                if not registry.enrollment_enabled:
                    raise MobileAuthError(
                        "enrollment_closed", "New App Attest enrollment is closed"
                    )
            elif not registry.has_key(payload.key_id):
                raise MobileAuthError(
                    "key_unknown", "App Attest key is not registered"
                )
            challenge = challenges.issue(
                purpose=payload.purpose, key_id=payload.key_id
            )
        except MobileAuthError as error:
            raise_mobile_error(error)
        return JSONResponse(
            {
                "schema_version": 1,
                "challenge_id": challenge.identifier,
                "challenge": challenge.encoded_value,
                "expires_in_seconds": settings.mobile_challenge_ttl_seconds,
            }
        )

    @app.post("/api/v1/mobile/attest")
    async def mobile_attest(payload: MobileAttestationRequest) -> JSONResponse:
        registry, challenges = require_mobile_services()
        try:
            challenge = challenges.consume(
                identifier=payload.challenge_id,
                purpose="attest",
                key_id=payload.key_id,
            )
            await asyncio.to_thread(
                registry.register,
                key_id=payload.key_id,
                attestation_object=payload.attestation,
                challenge=challenge.value,
            )
        except MobileAuthError as error:
            raise_mobile_error(error)
        return JSONResponse({"schema_version": 1, "registered": True})

    async def verify_mobile_assertion(
        payload: MobileAssertionRequest, *, purpose: str
    ) -> None:
        registry, challenges = require_mobile_services()
        try:
            challenge = challenges.consume(
                identifier=payload.challenge_id,
                purpose=purpose,
                key_id=payload.key_id,
            )
            await asyncio.to_thread(
                registry.verify_assertion,
                key_id=payload.key_id,
                assertion_object=payload.assertion,
                client_data=canonical_client_data(challenge),
            )
        except MobileAuthError as error:
            raise_mobile_error(error)

    @app.post("/api/v1/mobile/capacity")
    async def mobile_capacity(payload: MobileAssertionRequest) -> JSONResponse:
        await verify_mobile_assertion(payload, purpose="capacity")
        return JSONResponse(mobile_snapshot(await service.snapshot()))

    @app.post("/api/v1/mobile/refresh")
    async def mobile_refresh(payload: MobileAssertionRequest) -> JSONResponse:
        await verify_mobile_assertion(payload, purpose="refresh")
        result = await service.request_manual_probe()
        return JSONResponse(
            {
                "schema_version": 1,
                "probe_started": bool(result.get("probe_started")),
                "reason": result.get("reason"),
                "retry_after_seconds": result.get("retry_after_seconds"),
                "snapshot": mobile_snapshot(result["snapshot"]),
            }
        )

    return app
