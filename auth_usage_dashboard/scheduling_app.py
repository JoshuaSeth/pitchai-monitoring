# Copyright (c) 2026 PitchAI. All rights reserved.
"""Protected aggregate scheduling-capacity endpoint for the queue drainer."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

from . import app as dashboard_app
from .scheduling_capacity import build_scheduling_capacity_snapshot
from .service import CapacityService
from .settings import DashboardSettings
from .source import BrokerStateSource

if TYPE_CHECKING:
    from fastapi import FastAPI

    from .service import StateSource
    from .timeseries_types import JsonObject

_ALLOWED_IDENTITY_DOMAIN = "pitchai.net"
_MAX_EMAIL_LENGTH = 254
_VISIBLE_ASCII_MINIMUM = 33
_VISIBLE_ASCII_MAXIMUM = 126
_RequestClass = Request


def create_scheduling_app(
    settings: DashboardSettings | None = None,
    *,
    source: StateSource | None = None,
    service: CapacityService | None = None,
) -> FastAPI:
    """Extend the operator dashboard with its aggregate scheduler contract.

    Returns:
        The existing protected dashboard with one additional read-only route.
    """
    selected_settings = settings or DashboardSettings.from_env()
    selected_source = source or BrokerStateSource(
        data_dir=selected_settings.broker_data_dir,
        broker_url=selected_settings.broker_url,
        admin_token=selected_settings.broker_admin_token,
        request_timeout_seconds=selected_settings.request_timeout_seconds,
    )
    selected_service = service or CapacityService(selected_settings, selected_source)
    application = dashboard_app.create_app(
        selected_settings,
        source=selected_source,
        service=selected_service,
    )

    async def scheduling_capacity(request: Request) -> JSONResponse:
        _require_operator(selected_settings, request)
        snapshot = cast("JsonObject", await selected_service.snapshot())
        return JSONResponse(build_scheduling_capacity_snapshot(snapshot))

    application.add_api_route(
        "/api/v1/scheduling-capacity",
        scheduling_capacity,
        methods=["GET"],
    )
    return application


def _require_operator(settings: DashboardSettings, request: Request) -> None:
    """Require one trusted PitchAI proxy identity.

    Raises:
        HTTPException: If the proxy identity is absent or outside PitchAI.
        TypeError: If FastAPI supplies an invalid request value.
    """
    raw_request = cast("object", request)
    if not isinstance(raw_request, _RequestClass):
        message = "scheduler endpoint requires a Starlette request"
        raise TypeError(message)
    if not settings.require_proxy_auth:
        return
    raw_email = request.headers.get(settings.proxy_auth_header)
    if _normalize_pitchai_email(raw_email) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="PitchAI Entra SSO identity required",
        )


def _normalize_pitchai_email(raw_email: str | None) -> str | None:
    if raw_email is None or raw_email != raw_email.strip() or len(raw_email) > _MAX_EMAIL_LENGTH:
        return None
    email = raw_email.lower()
    local_part, separator, domain = email.rpartition("@")
    valid_structure = (
        email.count("@") == 1 and separator == "@" and bool(local_part) and domain == _ALLOWED_IDENTITY_DOMAIN
    )
    if not valid_structure:
        return None
    if any(ord(character) < _VISIBLE_ASCII_MINIMUM or ord(character) > _VISIBLE_ASCII_MAXIMUM for character in email):
        return None
    return email
