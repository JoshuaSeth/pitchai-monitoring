# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed settings, source, and assertion helpers for native API tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

from ._mobile_test_crypto import (
    APP_ID,
    APP_ID_PREFIX,
    BUNDLE_ID,
)
from .mobile_registry import AppAttestRegistry, RegistryConfiguration
from .mobile_settings import (
    AppAttestSettings,
    ChallengeSettings,
    MobileApplication,
    MobileSettings,
)
from .settings import DashboardSettings

if TYPE_CHECKING:
    from pathlib import Path

    from ._mobile_test_crypto import AttestationCryptoFixture
    from .service import StateSource
    from .timeseries_types import JsonObject, JsonValue


class FakeSource:
    """Return one usable account containing deliberate secret canaries."""

    closed: bool

    def __init__(self) -> None:
        """Initialize the close-state marker."""
        self.closed = False

    @staticmethod
    def read_accounts() -> list[JsonObject]:
        """Return one current account record."""
        now = datetime.now(UTC)
        metadata: JsonObject = {
            "account_id": "must-never-escape",
            "label": "seth-primary",
            "enabled": True,
            "prefer_for_all_clients": True,
        }
        five_hour: JsonObject = {
            "used_percent": 20,
            "reset_at": (now + timedelta(hours=2)).isoformat(),
            "limit_window_seconds": 18_000,
        }
        weekly: JsonObject = {
            "used_percent": 40,
            "reset_at": (now + timedelta(days=3)).isoformat(),
            "limit_window_seconds": 604_800,
        }
        usage: JsonObject = {
            "email": "private-account@example.com",
            "plan_type": "pro",
            "rate_limit": {
                "primary_window": five_hour,
                "secondary_window": weekly,
            },
        }
        state: JsonObject = {
            "availability": "available",
            "last_probe_at": now.isoformat(),
            "usage": usage,
        }
        return [
            {
                "metadata": metadata,
                "auth_json": {"refresh_token": "must-never-escape"},
                "state": state,
            },
        ]

    @staticmethod
    def probe_accounts(_accounts: list[JsonObject]) -> dict[str, str]:
        """Return no synthetic safe-probe failures."""
        return {}

    @staticmethod
    def probe_analytics(_accounts: list[JsonObject]) -> dict[str, str]:
        """Return no synthetic analytics-probe failures."""
        return {}

    def close(self) -> None:
        """Record application-lifespan cleanup."""
        self.closed = True


def dashboard_settings(root: Path) -> DashboardSettings:
    """Return a safe local dashboard configuration for integration tests.

    Returns:
        The isolated legacy dashboard settings.
    """
    return DashboardSettings(
        broker_data_dir=root,
        broker_url="http://127.0.0.1:38188",
        broker_admin_token="",
        safe_probe_enabled=False,
        probe_on_startup=False,
        snapshot_refresh_seconds=300,
        manual_probe_min_interval_seconds=30,
        require_proxy_auth=True,
        history_file=None,
    )


def mobile_settings(
    root: Path,
    root_certificate: Path,
    *,
    enabled: bool = True,
    enrollment_enabled: bool = True,
) -> MobileSettings:
    """Return grouped native-client settings for one isolated test.

    Returns:
        The isolated native-client settings.
    """
    return MobileSettings(
        enabled=enabled,
        application=MobileApplication(
            app_id_prefix=APP_ID_PREFIX,
            bundle_id=BUNDLE_ID,
        ),
        app_attest=AppAttestSettings(
            environment="development",
            registry_file=root / "mobile-app-attest.json",
            root_certificate=root_certificate,
            enrollment_enabled=enrollment_enabled,
            max_keys=1,
        ),
        challenges=ChallengeSettings(ttl_seconds=120, max_pending=8),
        background_refresh_seconds=900,
    )


def app_attest_registry(
    root: Path,
    fixture: AttestationCryptoFixture,
    *,
    enrollment_enabled: bool = True,
) -> AppAttestRegistry:
    """Create one isolated registry bound to the test application.

    Returns:
        The initialized private registry.
    """
    return AppAttestRegistry(
        RegistryConfiguration(
            path=root / "mobile-app-attest.json",
            root_certificate_path=fixture.root_path,
            app_id=APP_ID,
            environment="development",
            max_keys=1,
            enrollment_enabled=enrollment_enabled,
        ),
    )


def as_state_source(source: FakeSource) -> StateSource:
    """Return the runtime fixture through the unchanged legacy protocol.

    Returns:
        The fixture narrowed to the legacy state-source protocol.
    """
    dynamic_source = cast("object", source)
    return cast("StateSource", dynamic_source)


def require_text(value: JsonValue, description: str) -> str:
    """Require one non-empty JSON string.

    Returns:
        The narrowed string.

    Raises:
        TypeError: If the value is not non-empty text.
    """
    if isinstance(value, str) and value:
        return value
    message = f"{description}: expected non-empty text"
    raise TypeError(message)


def require_integer(value: JsonValue, description: str) -> int:
    """Require one JSON integer.

    Returns:
        The narrowed integer.

    Raises:
        TypeError: If the value is not an integer.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    message = f"{description}: expected integer"
    raise TypeError(message)
