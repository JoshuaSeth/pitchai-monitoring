# Copyright (c) 2026 PitchAI. All rights reserved.
"""Live, redacted Codex authentication-broker capacity dashboard."""

from __future__ import annotations

import string
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, cast, final

from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from .app_runtime import APPLICATION_FACTORY, HEADER_FACTORY, HTTP_EXCEPTION_FACTORY, REQUEST_TYPE
from .service import CapacityService
from .settings import DashboardSettings
from .source import BrokerStateSource

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from starlette.middleware.base import RequestResponseEndpoint
    from starlette.requests import Request

    from .app_runtime import DashboardApplication
    from .service import StateSource
    from .timeseries_types import JsonObject
else:
    # FastAPI resolves endpoint annotations from this module's globals at runtime.
    Request = REQUEST_TYPE

ROOT = Path(__file__).resolve().parent
_ALLOWED_IDENTITY_DOMAIN = "pitchai.net"
_MAX_EMAIL_LENGTH = 254
_VISIBLE_ASCII = frozenset(string.ascii_letters + string.digits + string.punctuation)
_LOCAL_DEVELOPMENT_OPERATOR = "local-development@pitchai.net"
_HTTP_UNAUTHORIZED = 401
_HTTP_FORBIDDEN = 403
_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; base-uri 'none'; connect-src 'self'; font-src 'self'; "
    "form-action 'self'; frame-ancestors 'none'; img-src 'self' data:; object-src 'none'; "
    "script-src 'self'; style-src 'self'"
)
_REFRESH_ACTION_HEADER = cast(
    "str | None",
    cast("object", HEADER_FACTORY(None, alias="X-Auth-Usage-Action")),
)


def create_app(
    settings: DashboardSettings | None = None,
    *,
    source: StateSource | None = None,
    service: CapacityService | None = None,
) -> DashboardApplication:
    """Assemble the proxy-protected dashboard around one capacity service.

    Returns:
        The FastAPI application whose lifespan starts and stops the capacity service.
    """
    dashboard_settings = settings or DashboardSettings.from_env()
    state_source = source or BrokerStateSource(
        data_dir=dashboard_settings.broker_data_dir,
        broker_url=dashboard_settings.broker_url,
        admin_token=dashboard_settings.broker_admin_token,
        request_timeout_seconds=dashboard_settings.request_timeout_seconds,
    )
    capacity_service = service or CapacityService(dashboard_settings, state_source)

    @asynccontextmanager
    async def lifespan(application: DashboardApplication) -> AsyncGenerator[None]:
        application.state.capacity_service = capacity_service
        await capacity_service.start()
        try:
            yield
        finally:
            await capacity_service.stop()

    application = APPLICATION_FACTORY(
        title="PitchAI Codex Capacity",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    application.state.settings = dashboard_settings
    templates = Jinja2Templates(directory=str(ROOT / "templates"))
    application.state.templates = templates
    application.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
    _ = application.middleware("http")(_security_headers)
    routes = _DashboardRoutes(dashboard_settings, capacity_service, templates)
    application.add_api_route("/healthz", routes.healthz, methods=["GET"], response_model=None)
    application.add_api_route(
        "/robots.txt",
        routes.robots,
        methods=["GET"],
        response_model=None,
        response_class=Response,
    )
    application.add_api_route(
        "/",
        routes.dashboard,
        methods=["GET"],
        response_model=None,
        response_class=HTMLResponse,
    )
    application.add_api_route("/api/v1/capacity", routes.capacity, methods=["GET"], response_model=None)
    application.add_api_route("/api/v1/refresh", routes.refresh, methods=["POST"], response_model=None)
    return application


@final
class _DashboardRoutes:
    """Endpoints of the dashboard, bound to its settings, capacity service, and templates."""

    _settings: DashboardSettings
    _service: CapacityService
    _templates: Jinja2Templates

    def __init__(self, settings: DashboardSettings, service: CapacityService, templates: Jinja2Templates) -> None:
        """Bind the endpoint dependencies."""
        self._settings = settings
        self._service = service
        self._templates = templates

    async def healthz(self) -> JsonObject:
        """Report identity-free service health.

        Returns:
            Status, generation time, and broker-source staleness.
        """
        return await self._service.health()

    @staticmethod
    async def robots() -> Response:
        """Disallow every crawler.

        Returns:
            The plain-text robots policy.
        """
        return Response("User-agent: *\nDisallow: /\n", media_type="text/plain")

    async def dashboard(self, request: Request) -> Response:
        """Render the dashboard page for the authenticated operator.

        Returns:
            The HTML dashboard naming the operator.
        """
        actor = self._require_operator(request)
        return self._templates.TemplateResponse(
            request,
            "dashboard.html",
            {"title": "Codex Capacity", "actor": actor},
        )

    async def capacity(self, request: Request) -> Response:
        """Return the redacted capacity snapshot to an authenticated operator.

        Returns:
            The capacity snapshot as JSON.
        """
        _ = self._require_operator(request)
        return JSONResponse(await self._service.snapshot())

    async def refresh(self, request: Request, action: str | None = _REFRESH_ACTION_HEADER) -> Response:
        """Request a throttled safe probe for an authenticated operator.

        Returns:
            The probe decision and the refreshed snapshot as JSON.

        Raises:
            HTTP_EXCEPTION_FACTORY: If the explicit refresh action header is missing.
        """
        _ = self._require_operator(request)
        if action != "refresh":
            raise HTTP_EXCEPTION_FACTORY(status_code=_HTTP_FORBIDDEN, detail="missing refresh action header")
        return JSONResponse(await self._service.request_manual_probe())

    def _require_operator(self, request: Request) -> str:
        """Return the trusted operator identity.

        Returns:
            The proxy-asserted PitchAI e-mail, or a fixed local identity when proxy auth is off.

        Raises:
            HTTP_EXCEPTION_FACTORY: If the proxy did not assert a PitchAI identity.
        """
        if not self._settings.require_proxy_auth:
            return _LOCAL_DEVELOPMENT_OPERATOR
        email = _normalize_pitchai_email(request.headers.get(self._settings.proxy_auth_header))
        if email is None:
            raise HTTP_EXCEPTION_FACTORY(
                status_code=_HTTP_UNAUTHORIZED,
                detail="PitchAI Entra SSO identity required",
            )
        return email


async def _security_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
    response = await call_next(request)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Content-Security-Policy"] = _CONTENT_SECURITY_POLICY
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=()"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


def _normalize_pitchai_email(raw_email: str | None) -> str | None:
    """Accept exactly one visible-ASCII ``<local>@pitchai.net`` identity.

    Returns:
        The lower-cased address, or None when the header is absent, padded, too long, or foreign.
    """
    if raw_email is None or len(raw_email) > _MAX_EMAIL_LENGTH or raw_email != raw_email.strip():
        return None
    email = raw_email.lower()
    local_part, _, domain = email.rpartition("@")
    single_pitchai_identity = email.count("@") == 1 and bool(local_part) and domain == _ALLOWED_IDENTITY_DOMAIN
    if not single_pitchai_identity or not _VISIBLE_ASCII.issuperset(email):
        return None
    return email
