# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build strict reusable fixtures for dashboard capacity tests."""

from __future__ import annotations

from datetime import UTC as DATETIME_UTC
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, TypedDict, Unpack

from auth_usage_dashboard.capacity import parse_account
from tests.auth_test_contract import FixtureContractError

if TYPE_CHECKING:
    from auth_usage_dashboard.json_contract import JsonObject, JsonValue
    from auth_usage_dashboard.models import CapacityAccount

UTC = DATETIME_UTC
NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)


class AccountFixtureOptions(TypedDict, total=False):
    """Describe optional provider state for one account fixture."""

    availability: str
    enabled: bool
    five_used: float | None
    five_reset: datetime | None
    weekly_used: float | None
    weekly_reset: datetime | None
    last_probe: datetime | None
    reset_credits: JsonValue
    analytics: JsonValue
    routing_preferred: bool


def account_fixture(
    label: str,
    **options: Unpack[AccountFixtureOptions],
) -> JsonObject:
    """Build one broker-shaped account fixture without exposing secrets.

    Returns:
        The resulting value.

    """
    five_reset = options.get("five_reset") or NOW + timedelta(hours=3)
    weekly_reset = options.get("weekly_reset") or NOW + timedelta(days=6)
    last_probe = options.get("last_probe") or NOW - timedelta(seconds=30)
    five_used = options.get("five_used", 40)
    weekly_used = options.get("weekly_used", 20)
    primary: JsonObject = {
        "limit_window_seconds": 18_000,
        "reset_at": five_reset.isoformat(),
    }
    secondary: JsonObject = {
        "limit_window_seconds": 604_800,
        "reset_at": weekly_reset.isoformat(),
    }
    if five_used is not None:
        primary["used_percent"] = five_used
    if weekly_used is not None:
        secondary["used_percent"] = weekly_used
    reset_credits = options.get("reset_credits")
    state: JsonObject = {
        "availability": options.get("availability", "available"),
        "last_probe_at": last_probe.isoformat(),
        "refresh_token": "must-not-escape",
        "usage": {
            "email": label,
            "plan_type": "pro",
            "rate_limit": {
                "primary_window": primary,
                "secondary_window": secondary,
            },
            "rate_limit_reset_credits": reset_credits if reset_credits is not None else {"available_count": 2},
        },
    }
    analytics = options.get("analytics")
    if analytics is not None:
        state["analytics"] = analytics
    return {
        "metadata": {
            "account_id": f"id-{label}",
            "label": label,
            "enabled": options.get("enabled", True),
            "prefer_for_all_clients": options.get("routing_preferred", False),
            "broker_secret": "must-not-escape",
        },
        "state": state,
        "auth_json": {"access_token": "must-not-escape"},
    }


def parse_fixture(raw: JsonObject) -> CapacityAccount:
    """Parse one account fixture with the shared deterministic policy.

    Returns:
        The resulting value.

    """
    return parse_account(
        raw,
        now=NOW,
        stale_after_seconds=600,
        min_five_hour_remaining_percent=10,
    )


def nested_object(container: JsonObject, *keys: str) -> JsonObject:
    """Return a required nested object from a test fixture.

    Raises:
        FixtureContractError: If a nested fixture field is not an object.

    """
    current = container
    for key in keys:
        value = current.get(key)
        if not isinstance(value, dict):
            msg = f"test fixture field {key} must be an object"
            raise FixtureContractError(msg)
        current = value
    return current
