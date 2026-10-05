# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed redacted-broker fixtures shared by the legacy capacity dashboard tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ._timeseries_test_fixtures import require_array
from .capacity import build_dashboard_snapshot, parse_account
from .timeseries_types import require_object

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import TypedDict, Unpack

    from .timeseries_types import JsonObject, JsonValue

    class RawAccountOptions(TypedDict, total=False):
        """Optional overrides for one raw broker account."""

        now: datetime
        account_id: str
        availability: str
        enabled: bool
        routing_preferred: bool
        five_used: float | None
        five_reset: datetime
        weekly_used: float | None
        weekly_reset: datetime
        last_probe: datetime
        credits: JsonObject
        analytics: JsonObject


NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
LEAK_MARKER = "must-not-escape"
FIVE_HOUR_SECONDS = 18_000
WEEK_SECONDS = 604_800
STALE_AFTER_SECONDS = 600
ANALYTICS_STALE_AFTER_SECONDS = 1_800
MIN_FIVE_HOUR_REMAINING_PERCENT = 10


def raw_account(label: str, **options: Unpack[RawAccountOptions]) -> JsonObject:
    """Return one broker account whose secret-bearing fields must never be exposed.

    Returns:
        Metadata, state, and auth JSON exactly as the broker stores them.
    """
    now = options.get("now", NOW)
    five_reset = options.get("five_reset", now + timedelta(hours=3))
    weekly_reset = options.get("weekly_reset", now + timedelta(days=6))
    primary: JsonObject = {"limit_window_seconds": FIVE_HOUR_SECONDS, "reset_at": five_reset.isoformat()}
    secondary: JsonObject = {"limit_window_seconds": WEEK_SECONDS, "reset_at": weekly_reset.isoformat()}
    five_used = options.get("five_used", 40)
    weekly_used = options.get("weekly_used", 20)
    if five_used is not None:
        primary["used_percent"] = five_used
    if weekly_used is not None:
        secondary["used_percent"] = weekly_used
    usage: JsonObject = {
        "email": label,
        "plan_type": "pro",
        "rate_limit": {"primary_window": primary, "secondary_window": secondary},
        "rate_limit_reset_credits": options.get("credits", {"available_count": 2}),
    }
    state: JsonObject = {
        "availability": options.get("availability", "available"),
        "last_probe_at": options.get("last_probe", now - timedelta(seconds=30)).isoformat(),
        "refresh_token": LEAK_MARKER,
        "usage": usage,
    }
    if "analytics" in options:
        state["analytics"] = options["analytics"]
    metadata: JsonObject = {
        "account_id": options.get("account_id", f"id-{label}"),
        "label": label,
        "enabled": options.get("enabled", True),
        "prefer_for_all_clients": options.get("routing_preferred", False),
        "broker_secret": LEAK_MARKER,
    }
    return {"metadata": metadata, "state": state, "auth_json": {"access_token": LEAK_MARKER}}


def analytics_state(
    updated_at: datetime,
    *,
    buckets: list[JsonValue],
    reset_credits: list[JsonValue],
    available_count: int,
    lifetime_tokens: int | None = None,
) -> JsonObject:
    """Return one redacted analytics probe result refreshed at ``updated_at``.

    Returns:
        Token-usage buckets and reset-bank credits as the broker records them.
    """
    moment = updated_at.isoformat()
    summary: JsonObject = {} if lifetime_tokens is None else {"lifetime_tokens": lifetime_tokens}
    return {
        "last_probe_at": moment,
        "token_usage_updated_at": moment,
        "token_usage": {"summary": summary, "daily_usage_buckets": buckets},
        "reset_credits_updated_at": moment,
        "reset_credits": {"available_count": available_count, "credits": reset_credits},
        "errors": {},
    }


def keep_only_weekly_window(raw: JsonObject) -> None:
    """Make the weekly window the provider's only, primary-slot rate-limit window."""
    rate_limit = member(raw, "state", "usage", "rate_limit")
    rate_limit["primary_window"] = rate_limit.pop("secondary_window")


def add_usage_credits(raw: JsonObject, *, balance: str, overage_reached: bool, spending_reached: bool) -> None:
    """Attach purchased usage credits and the spend-control state to one raw account."""
    usage = member(raw, "state", "usage")
    usage["credits"] = {
        "has_credits": True,
        "unlimited": False,
        "balance": balance,
        "overage_limit_reached": overage_reached,
    }
    usage["spend_control"] = {"reached": spending_reached}


def parse_raw(raw: JsonObject) -> JsonObject:
    """Parse one raw account with the production staleness and floor thresholds.

    Returns:
        The redacted dashboard account.
    """
    parsed = parse_account(
        raw,
        now=NOW,
        stale_after_seconds=STALE_AFTER_SECONDS,
        min_five_hour_remaining_percent=MIN_FIVE_HOUR_REMAINING_PERCENT,
    )
    return json_object(parsed)


def snapshot_of(accounts: list[JsonObject]) -> JsonObject:
    """Build the dashboard snapshot for raw accounts at the fixed test moment.

    Returns:
        The complete redacted dashboard snapshot.
    """
    snapshot = build_dashboard_snapshot(
        accounts,
        now=NOW,
        stale_after_seconds=STALE_AFTER_SECONDS,
        analytics_stale_after_seconds=ANALYTICS_STALE_AFTER_SECONDS,
        min_five_hour_remaining_percent=MIN_FIVE_HOUR_REMAINING_PERCENT,
    )
    return json_object(snapshot)


def json_object(value: Mapping[str, JsonValue]) -> JsonObject:
    """Return an independent JSON object copy of one production result.

    Returns:
        A mutable JSON object, whatever mapping type the producer declares.
    """
    return dict(value)


def member(container: JsonObject, *path: str) -> JsonObject:
    """Return the nested JSON object reached by following ``path`` keys.

    Returns:
        The nested object, validated at every step.
    """
    current = container
    for key in path:
        current = require_object(current.get(key), description=key)
    return current


def objects(value: JsonValue, description: str) -> list[JsonObject]:
    """Return a JSON array whose every element must be an object.

    Returns:
        The validated objects in their original order.
    """
    array = require_array(value, description)
    return [require_object(item, description=description) for item in array]


def text(value: JsonValue, description: str) -> str:
    """Return one required JSON string.

    Returns:
        The string value.

    Raises:
        TypeError: If the value is not a string.
    """
    if isinstance(value, str):
        return value
    message = f"{description}: expected string, got {value!r}"
    raise TypeError(message)


def integer(value: JsonValue, description: str) -> int:
    """Return one required JSON integer, rejecting booleans.

    Returns:
        The integer value.

    Raises:
        TypeError: If the value is not an integer.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    message = f"{description}: expected integer, got {value!r}"
    raise TypeError(message)
