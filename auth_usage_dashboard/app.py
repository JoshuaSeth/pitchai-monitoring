from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .service import CapacityService, StateSource
from .settings import DashboardSettings
from .source import BrokerStateSource


ROOT = Path(__file__).resolve().parent
_ALLOWED_IDENTITY_DOMAIN = "pitchai.net"
_MAX_EMAIL_LENGTH = 254


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
) -> FastAPI:
    settings = settings or DashboardSettings.from_env()
    source = source or BrokerStateSource(
        data_dir=settings.broker_data_dir,
        broker_url=settings.broker_url,
        admin_token=settings.broker_admin_token,
        request_timeout_seconds=settings.request_timeout_seconds,
    )
    service = service or CapacityService(settings, source)

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

    return app
