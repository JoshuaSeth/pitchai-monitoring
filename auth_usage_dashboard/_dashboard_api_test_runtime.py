# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed application, client, and broker-source boundary for legacy dashboard tests."""

from __future__ import annotations

import copy
import secrets
from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

from .scheduling_web_runtime import dashboard_app_factory
from .service import CapacityService
from .settings import DashboardSettings

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path
    from types import TracebackType
    from typing import Self

    from .scheduling_web_runtime import Application, Response
    from .timeseries_types import JsonObject

BROKER_URL = "http://127.0.0.1:38188"
OPERATOR_HEADERS = {"X-PitchAI-Email": "operator@pitchai.net"}
REFRESH_HEADERS = {**OPERATOR_HEADERS, "X-Auth-Usage-Action": "refresh"}


class DashboardClient(Protocol):
    """Lifespan-aware synchronous client for the legacy dashboard routes."""

    def __enter__(self) -> Self:
        """Start the application lifespan and return the client."""
        raise NotImplementedError

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Stop the application lifespan."""
        raise NotImplementedError

    def get(self, path: str, *, headers: Mapping[str, str] | None = None) -> Response:
        """Issue one local GET request."""
        raise NotImplementedError

    def post(self, path: str, *, headers: Mapping[str, str] | None = None) -> Response:
        """Issue one local POST request without a body."""
        raise NotImplementedError


class _DashboardClientFactory(Protocol):
    def __call__(self, application: Application) -> DashboardClient:
        """Create one client bound to the dashboard application."""
        raise NotImplementedError

    def factory_marker(self) -> None:
        """Identify the dynamic client contract to static tooling."""
        raise NotImplementedError


_TESTCLIENT_MODULE = cast("dict[str, object]", vars(import_module("fastapi.testclient")))
DASHBOARD_CLIENT = cast("_DashboardClientFactory", _TESTCLIENT_MODULE["TestClient"])


class StaticBrokerSource:
    """Serve fixed raw broker accounts and record every probe batch."""

    accounts: list[JsonObject]
    probe_batches: list[int]
    analytics_probe_batches: list[int]
    closed: bool

    def __init__(self, accounts: list[JsonObject]) -> None:
        """Hold the raw accounts every read returns a fresh copy of."""
        self.accounts = accounts
        self.probe_batches = []
        self.analytics_probe_batches = []
        self.closed = False

    def read_accounts(self) -> list[JsonObject]:
        """Return an independent copy of the raw broker accounts."""
        return copy.deepcopy(self.accounts)

    def probe_accounts(self, accounts: list[JsonObject]) -> dict[str, str]:
        """Record one safe-probe batch without reporting errors.

        Returns:
            No per-account probe errors.
        """
        self.probe_batches.append(len(accounts))
        return {}

    def probe_analytics(self, accounts: list[JsonObject]) -> dict[str, str]:
        """Record one analytics-probe batch without reporting errors.

        Returns:
            No per-account probe errors.
        """
        self.analytics_probe_batches.append(len(accounts))
        return {}

    def close(self) -> None:
        """Record that the dashboard released its broker source."""
        self.closed = True


def legacy_settings(root: Path, *, safe_probe: bool = False) -> DashboardSettings:
    """Return proxy-protected settings whose safe probing is optionally enabled.

    Returns:
        Settings with a one-minute probe interval and a thirty-second manual throttle.
    """
    return DashboardSettings(
        broker_data_dir=root,
        broker_url=BROKER_URL,
        broker_admin_token=secrets.token_hex(16),
        safe_probe_enabled=safe_probe,
        probe_on_startup=safe_probe,
        snapshot_refresh_seconds=300,
        safe_probe_interval_seconds=60,
        manual_probe_min_interval_seconds=30,
        stale_after_seconds=600,
        require_proxy_auth=True,
    )


def dashboard_application(settings: DashboardSettings, source: StaticBrokerSource) -> Application:
    """Compose the production dashboard around one static broker source.

    Returns:
        The dashboard application with its default capacity service.
    """
    service = CapacityService(settings, source)
    return dashboard_app_factory(settings, source=source, service=service)
