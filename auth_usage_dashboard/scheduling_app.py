# Copyright (c) 2026 PitchAI. All rights reserved.
"""Protected aggregate scheduling-capacity endpoint for the queue drainer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

from .scheduling_capacity import build_scheduling_capacity_snapshot
from .scheduling_web_runtime import (
    HTTPException,
    dashboard_app_factory,
    header_factory,
    json_response_factory,
)
from .service import CapacityService
from .settings import DashboardSettings
from .source import BrokerStateSource

if TYPE_CHECKING:
    from .scheduling_web_runtime import Application, Response
    from .service import StateSource
    from .timeseries_types import JsonObject

_ALLOWED_IDENTITY_DOMAIN = "pitchai.net"
_MAX_EMAIL_LENGTH = 254
_VISIBLE_ASCII_MINIMUM = 33
_VISIBLE_ASCII_MAXIMUM = 126
_HTTP_UNAUTHORIZED = 401


class _CapacitySnapshotReader(Protocol):
    """Strict snapshot surface consumed by the scheduling projection."""

    async def snapshot(self) -> JsonObject:
        """Return the current operator snapshot."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


def create_scheduling_app(
    settings: DashboardSettings | None = None,
    *,
    source: StateSource | None = None,
    service: CapacityService | None = None,
) -> Application:
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
    application = dashboard_app_factory(
        selected_settings,
        source=selected_source,
        service=selected_service,
    )
    capacity_reader = cast(
        "_CapacitySnapshotReader",
        cast("object", selected_service),
    )
    identity_header = cast(
        "str | None",
        cast(
            "object",
            header_factory(None, alias=selected_settings.proxy_auth_header),
        ),
    )

    async def scheduling_capacity(
        proxy_identity: str | None = identity_header,
    ) -> Response:
        _require_operator(selected_settings, proxy_identity)
        snapshot = await capacity_reader.snapshot()
        payload = build_scheduling_capacity_snapshot(snapshot)
        return json_response_factory(payload)

    application.add_api_route(
        "/api/v1/scheduling-capacity",
        scheduling_capacity,
        methods=["GET"],
        response_model=None,
    )
    return application


def _require_operator(settings: DashboardSettings, raw_email: str | None) -> None:
    """Require one trusted PitchAI proxy identity.

    Raises:
        HTTPException: If the proxy identity is absent or outside PitchAI.
    """
    if not settings.require_proxy_auth:
        return
    if _normalize_pitchai_email(raw_email) is None:
        raise HTTPException(
            status_code=_HTTP_UNAUTHORIZED,
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
