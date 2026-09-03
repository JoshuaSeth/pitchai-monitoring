# Copyright (c) 2026 PitchAI. All rights reserved.
"""Protected aggregate scheduling-capacity endpoint for the queue drainer."""

from __future__ import annotations

from asyncio import to_thread
from functools import partial
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

from .history import UsageSampleStore
from .luna_reserve_gateway import read_luna_reserve_snapshot
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
    from collections.abc import Callable

    from .scheduling_web_runtime import Application, Response
    from .service import StateSource
    from .timeseries_types import JsonObject

_ALLOWED_IDENTITY_DOMAIN = "pitchai.net"
_MAX_EMAIL_LENGTH = 254
_VISIBLE_ASCII_MINIMUM = 33
_VISIBLE_ASCII_MAXIMUM = 126
_HTTP_UNAUTHORIZED = 401


@runtime_checkable
class _RawAccountReader(Protocol):
    """Strict read-only inventory surface used to prove routing tiers."""

    def read_accounts(self) -> list[JsonObject]:
        """Return current raw account metadata and state."""
        raise NotImplementedError

    def close(self) -> None:
        """Release resources owned by the inventory reader."""
        raise NotImplementedError


def create_scheduling_app(
    settings: DashboardSettings | None = None,
    *,
    source: StateSource | None = None,
    service: CapacityService | None = None,
    luna_capacity_reader: Callable[[], JsonObject] | None = None,
) -> Application:
    """Extend the operator dashboard with its aggregate scheduler contract.

    Returns:
        The existing protected dashboard with aggregate scheduler and reserve routes.
    """
    selected_settings = settings or DashboardSettings.from_env()
    selected_source = source or BrokerStateSource(
        data_dir=selected_settings.broker_data_dir,
        broker_url=selected_settings.broker_url,
        admin_token=selected_settings.broker_admin_token,
        request_timeout_seconds=selected_settings.request_timeout_seconds,
    )
    selected_service = service or CapacityService(selected_settings, selected_source)
    selected_luna_reader = luna_capacity_reader or partial(
        read_luna_reserve_snapshot,
        broker_url=selected_settings.broker_url,
        admin_token=selected_settings.broker_admin_token,
        request_timeout_seconds=selected_settings.request_timeout_seconds,
    )
    application = dashboard_app_factory(
        selected_settings,
        source=selected_source,
        service=selected_service,
    )
    source_object = cast("object", selected_source)
    raw_account_reader = (
        source_object if isinstance(source_object, _RawAccountReader) else None
    )
    sample_store = (
        UsageSampleStore(
            selected_settings.history_file,
            retention_days=selected_settings.history_retention_days,
            sample_interval_seconds=selected_settings.history_sample_interval_seconds,
        )
        if selected_settings.history_file is not None
        else None
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
        snapshot = await selected_service.snapshot()
        raw_accounts = None
        usage_samples = None
        if raw_account_reader is not None:
            raw_accounts = await to_thread(raw_account_reader.read_accounts)
            if sample_store is not None:
                usage_samples = cast(
                    "list[JsonObject]",
                    cast("object", await to_thread(sample_store.read)),
                )
        payload = build_scheduling_capacity_snapshot(
            snapshot,
            raw_accounts=raw_accounts,
            usage_samples=usage_samples,
        )
        return json_response_factory(payload)

    async def luna_reserve_capacity(
        proxy_identity: str | None = identity_header,
    ) -> Response:
        _require_operator(selected_settings, proxy_identity)
        payload = await to_thread(selected_luna_reader)
        return json_response_factory(payload)

    application.add_api_route(
        "/api/v1/scheduling-capacity",
        scheduling_capacity,
        methods=["GET"],
        response_model=None,
    )
    application.add_api_route(
        "/api/v1/luna-reserve",
        luna_reserve_capacity,
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
    if (
        raw_email is None
        or raw_email != raw_email.strip()
        or len(raw_email) > _MAX_EMAIL_LENGTH
    ):
        return None
    email = raw_email.lower()
    local_part, separator, domain = email.rpartition("@")
    valid_structure = (
        email.count("@") == 1
        and separator == "@"
        and bool(local_part)
        and domain == _ALLOWED_IDENTITY_DOMAIN
    )
    if not valid_structure:
        return None
    if any(
        ord(character) < _VISIBLE_ASCII_MINIMUM
        or ord(character) > _VISIBLE_ASCII_MAXIMUM
        for character in email
    ):
        return None
    return email
