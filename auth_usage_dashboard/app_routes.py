# Copyright (c) 2026 PitchAI. All rights reserved.
"""Register authenticated dashboard routes and response protections."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated, Protocol, TypedDict

import fastapi
from fastapi.responses import HTMLResponse, JSONResponse, Response

if TYPE_CHECKING:
    from collections.abc import Awaitable, Iterator

    from .service import CapacityService
    from .settings import DashboardSettings

_ALLOWED_IDENTITY_DOMAIN = "pitchai.net"
_FIRST_PRINTABLE_ASCII = 33
_LAST_PRINTABLE_ASCII = 126
_MAX_EMAIL_LENGTH = 254


class DashboardTemplateContext(TypedDict):
    """Define the complete context rendered by the dashboard template."""

    request: fastapi.Request
    title: str
    actor: str


class DashboardTemplate(Protocol):
    """Constrain the Jinja operations available to dashboard rendering."""

    def render(self, context: DashboardTemplateContext, /) -> str:
        """Render one complete HTML document."""
        raise NotImplementedError

    def generate(self, context: DashboardTemplateContext, /) -> Iterator[str]:
        """Declare the template's incremental rendering capability."""
        raise NotImplementedError


type TemplateLoader = Callable[[str], DashboardTemplate]


def _normalize_pitchai_email(raw_email: str | None) -> str | None:
    if raw_email is None or raw_email != raw_email.strip() or len(raw_email) > _MAX_EMAIL_LENGTH:
        return None
    email = raw_email.lower()
    local_part, separator, domain = email.rpartition("@")
    valid_address = (
        email.count("@") == 1 and separator == "@" and bool(local_part) and domain == _ALLOWED_IDENTITY_DOMAIN
    )
    if not valid_address:
        return None
    if any(not _FIRST_PRINTABLE_ASCII <= ord(character) <= _LAST_PRINTABLE_ASCII for character in email):
        return None
    return email


class DashboardRoutes:
    """Bind authenticated route handlers to one configured capacity service."""

    def __init__(
        self,
        *,
        settings: DashboardSettings,
        service: CapacityService,
        template_loader: TemplateLoader,
    ) -> None:
        """Store the dependencies shared by every route handler."""
        self._settings: DashboardSettings = settings
        self._service: CapacityService = service
        self._template_loader: TemplateLoader = template_loader

    @staticmethod
    async def security_headers(
        request: fastapi.Request,
        call_next: Callable[[fastapi.Request], Awaitable[Response]],
    ) -> Response:
        """Apply no-store and browser-isolation headers to every response.

        Returns:
            The protected response.

        """
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

    def require_operator(self, request: fastapi.Request) -> str:
        """Return the verified PitchAI operator identity.

        Returns:
            The normalized operator email.

        Raises:
            HTTPException: If the proxy identity is absent or invalid.

        """
        if not self._settings.require_proxy_auth:
            return "local-development@pitchai.net"
        email = _normalize_pitchai_email(
            request.headers.get(self._settings.proxy_auth_header),
        )
        if email is None:
            raise fastapi.HTTPException(
                status_code=fastapi.status.HTTP_401_UNAUTHORIZED,
                detail="PitchAI Entra SSO identity required",
            )
        return email

    async def healthz(self) -> JSONResponse:
        """Return the service health payload.

        Returns:
            The current health payload.

        """
        return JSONResponse(await self._service.health())

    @staticmethod
    def robots() -> Response:
        """Disallow crawler indexing.

        Returns:
            The restrictive robots response.

        """
        return Response("User-agent: *\nDisallow: /\n", media_type="text/plain")

    def dashboard(self, request: fastapi.Request) -> HTMLResponse:
        """Render the authenticated operator dashboard.

        Returns:
            The rendered dashboard response.

        """
        actor = self.require_operator(request)
        template = self._template_loader("dashboard.html")
        context: DashboardTemplateContext = {
            "request": request,
            "title": "Codex Capacity",
            "actor": actor,
        }
        return HTMLResponse(template.render(context))

    async def capacity(self, request: fastapi.Request) -> JSONResponse:
        """Return the authenticated capacity snapshot.

        Returns:
            The current capacity response.

        """
        _ = self.require_operator(request)
        return JSONResponse(await self._service.snapshot())

    async def refresh(
        self,
        request: fastapi.Request,
        action: Annotated[
            str | None,
            fastapi.Header(alias="X-Auth-Usage-Action"),
        ] = None,
    ) -> JSONResponse:
        """Request an authenticated manual probe.

        Returns:
            The manual probe result.

        Raises:
            HTTPException: If the explicit refresh action is absent.

        """
        _ = self.require_operator(request)
        if action != "refresh":
            raise fastapi.HTTPException(
                status_code=fastapi.status.HTTP_403_FORBIDDEN,
                detail="missing refresh action header",
            )
        return JSONResponse(await self._service.request_manual_probe())

    def register(self, app: fastapi.FastAPI) -> None:
        """Register every dashboard middleware and route on the application."""
        _ = app.middleware("http")(self.security_headers)
        app.add_api_route("/healthz", self.healthz, methods=["GET"])
        app.add_api_route(
            "/robots.txt",
            self.robots,
            methods=["GET"],
            response_class=Response,
        )
        app.add_api_route(
            "/",
            self.dashboard,
            methods=["GET"],
            response_class=HTMLResponse,
        )
        app.add_api_route("/api/v1/capacity", self.capacity, methods=["GET"])
        app.add_api_route("/api/v1/refresh", self.refresh, methods=["POST"])
