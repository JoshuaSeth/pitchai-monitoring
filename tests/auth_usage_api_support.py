# Copyright (c) 2026 PitchAI. All rights reserved.
"""Provide strict reusable fixtures for dashboard HTTP API tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC as DATETIME_UTC
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, final

from auth_usage_dashboard.json_contract import decode_document
from auth_usage_dashboard.settings import DashboardSettings
from tests.auth_test_contract import FixtureContractError

if TYPE_CHECKING:
    from pathlib import Path

    import httpx

    from auth_usage_dashboard.json_contract import JsonObject, JsonValue

UTC = DATETIME_UTC
TEST_BROKER_BEARER = "test-admin-token"


@final
class FakeSource:
    """Provide deterministic in-memory accounts at the dashboard source boundary."""

    def __init__(self, accounts: list[JsonObject]) -> None:
        """Initialize the source and probe counters."""
        self.accounts = accounts
        self.probe_count = 0
        self.analytics_probe_count = 0
        self.closed = False

    def read_accounts(self) -> list[JsonObject]:
        """Return an isolated copy of every configured account."""
        return deepcopy(self.accounts)

    def probe_accounts(self, accounts: list[JsonObject]) -> dict[str, str]:
        """Record a legacy safe-probe request.

        Returns:
            The resulting collection.

        """
        _ = accounts
        self.probe_count += 1
        return {}

    def probe_analytics(self, accounts: list[JsonObject]) -> dict[str, str]:
        """Record an analytics safe-probe request.

        Returns:
            The resulting collection.

        """
        _ = accounts
        self.analytics_probe_count += 1
        return {}

    def close(self) -> None:
        """Record closure of the source lifecycle."""
        self.closed = True


def raw_account() -> JsonObject:
    """Build one current broker state fixture with safe analytics.

    Returns:
        The resulting value.

    """
    now = datetime.now(UTC)
    return {
        "metadata": {
            "account_id": "internal-id",
            "label": "safe@example.com",
            "enabled": True,
        },
        "state": {
            "availability": "available",
            "last_probe_at": now.isoformat(),
            "usage": {
                "email": "safe@example.com",
                "rate_limit": {
                    "primary_window": {
                        "used_percent": 25,
                        "reset_at": (now + timedelta(hours=4)).isoformat(),
                        "limit_window_seconds": 18_000,
                    },
                    "secondary_window": {
                        "used_percent": 10,
                        "reset_at": (now + timedelta(days=6)).isoformat(),
                        "limit_window_seconds": 604_800,
                    },
                },
                "rate_limit_reset_credits": {"available_count": 1},
            },
            "analytics": {
                "last_probe_at": now.isoformat(),
                "token_usage_updated_at": now.isoformat(),
                "token_usage": {
                    "summary": {"lifetime_tokens": 1_000},
                    "daily_usage_buckets": [
                        {"start_date": now.date().isoformat(), "tokens": 100},
                    ],
                },
                "reset_credits_updated_at": now.isoformat(),
                "reset_credits": {"available_count": 1, "credits": []},
                "errors": {},
            },
        },
    }


def response_object(response: httpx.Response) -> JsonObject:
    """Decode one test response through the recursive JSON boundary.

    Returns:
        The resulting value.

    Raises:
        FixtureContractError: If the response is not an object.

    """
    value = decode_document(response.content)
    if not isinstance(value, dict):
        msg = "response must contain a JSON object"
        raise FixtureContractError(msg)
    return value


def required_object(container: JsonObject, key: str) -> JsonObject:
    """Require one nested response object.

    Returns:
        The resulting value.

    Raises:
        FixtureContractError: If the response field is not an object.

    """
    value = container.get(key)
    if not isinstance(value, dict):
        msg = f"{key} must contain an object"
        raise FixtureContractError(msg)
    return value


def required_array(container: JsonObject, key: str) -> list[JsonValue]:
    """Require one nested response array.

    Returns:
        The resulting collection.

    Raises:
        FixtureContractError: If the response field is not an array.

    """
    value = container.get(key)
    if not isinstance(value, list):
        msg = f"{key} must contain an array"
        raise FixtureContractError(msg)
    return value


def required_array_object(values: list[JsonValue], index: int) -> JsonObject:
    """Require one object at an array index.

    Returns:
        The resulting value.

    Raises:
        FixtureContractError: If the response array item is not an object.

    """
    value = values[index]
    if not isinstance(value, dict):
        msg = f"array item {index} must contain an object"
        raise FixtureContractError(msg)
    return value


def dashboard_settings(
    tmp_path: Path,
    *,
    safe_probe: bool = False,
) -> DashboardSettings:
    """Build strict dashboard settings for one isolated API test.

    Returns:
        The resulting value.

    """
    return DashboardSettings(
        broker_data_dir=tmp_path,
        broker_url="http://127.0.0.1:38188",
        broker_admin_token=TEST_BROKER_BEARER,
        safe_probe_enabled=safe_probe,
        probe_on_startup=safe_probe,
        snapshot_refresh_seconds=300,
        safe_probe_interval_seconds=60,
        manual_probe_min_interval_seconds=30,
        stale_after_seconds=600,
        require_proxy_auth=True,
    )
