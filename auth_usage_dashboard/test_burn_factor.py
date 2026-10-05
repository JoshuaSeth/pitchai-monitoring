# Copyright (c) 2026 PitchAI. All rights reserved.
"""Proof of the burn factor arithmetic, horizon capacity and window parsing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ._timeseries_test_fixtures import check, check_close, check_equal
from ._token_ledger_test_fixtures import value_error_text
from .burn_factor import build_burn_factors
from .burn_factor_capacity import AccountWindow, simulate
from .burn_factor_windows import parse_duration, parse_pairs
from .timeseries_types import optional_object, require_object

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
WEEK = timedelta(days=7)
HORIZON_LIMITS = (3_600, 14 * 86_400)


def test_durations_and_pairs_parse_and_reject_out_of_range_values() -> None:
    """Prove 30m/24h/6d style durations parse and bad pairs are rejected with a reason."""
    check_equal(parse_duration("30m", (300, 604_800)), 1_800, "minutes")
    check_equal(parse_duration("6d", HORIZON_LIMITS), 518_400, "days")
    pairs = parse_pairs("30m:24h, 24h:6d")
    check_equal([(pair.rolling, pair.horizon) for pair in pairs], [("30m", "24h"), ("24h", "6d")], "default pairs")
    check(
        "lie within" in value_error_text(lambda: parse_pairs("1m:24h")),
        "a rolling window under 5 minutes is refused",
    )
    check("rolling:horizon" in value_error_text(lambda: parse_pairs("30m")), "a pair needs both windows")
    check("between 1 and" in value_error_text(lambda: parse_pairs(",".join(["30m:1h"] * 7))), "at most six pairs")


def test_reset_three_hours_out_counts_only_burnable_leftover_then_a_full_window() -> None:
    """Prove Seth's example: leftover is usable for 3 hours, then a full window for the other 21."""
    account = AccountWindow(30.0, NOW + timedelta(hours=3), WEEK)
    capacity = simulate([account], start=NOW, rate=2.0, horizon_hours=24.0)
    check_close(capacity.left_now_points, 30.0, "points left now")
    check_close(capacity.reset_points, 100.0, "one reset inside the horizon")
    check_close(capacity.losses.at_resets, 24.0, "leftover not burnable before the reset expires")
    check_close(capacity.effective_points, 106.0, "30 - 24 + 100")
    check_close(capacity.runway_hours or 0.0, 53.0, "3 hours on the leftover, then 100 points at 2 per hour")


def test_fast_burn_reports_the_runway_until_the_first_shortfall() -> None:
    """Prove the runway is the moment demand first exceeds what is available."""
    account = AccountWindow(30.0, NOW + timedelta(hours=3), WEEK)
    capacity = simulate([account], start=NOW, rate=20.0, horizon_hours=24.0)
    runway = capacity.runway_hours
    check(runway is not None, "a fast burn runs short")
    check_close(runway or 0.0, 1.5, "30 points at 20 per hour last 1.5 hours")


def test_subscription_end_loses_the_leftover_and_stops_later_resets() -> None:
    """Prove an ending subscription forfeits its leftover and receives no reset after the end."""
    account = AccountWindow(40.0, NOW + timedelta(hours=20), timedelta(hours=5), NOW + timedelta(hours=10))
    capacity = simulate([account], start=NOW, rate=1.0, horizon_hours=48.0)
    check_equal(capacity.losses.subscription_end_count, 1, "one subscription ends")
    check_close(capacity.losses.at_subscription_ends, 30.0, "40 left minus 10 burned before the end")
    check_equal(capacity.reset_count, 0, "the reset after the end never happens")
    check_close(capacity.effective_points, 10.0, "only what was burned before the end counts")


def test_zero_burn_has_no_runway_limit_and_counts_unburned_leftovers_as_expiring() -> None:
    """Prove a pool with no burn never runs out and its leftovers expire at resets."""
    account = AccountWindow(70.0, NOW + timedelta(hours=1), WEEK)
    capacity = simulate([account], start=NOW, rate=0.0, horizon_hours=6.0)
    check(capacity.runway_hours is None, "no burn, no shortfall")
    check_close(capacity.losses.at_resets, 70.0, "nothing was burned before the reset")
    check_close(capacity.effective_points, 100.0, "the fresh window remains")


def _account(label: str, used: float, reset_at: datetime) -> JsonObject:
    window: JsonObject = {
        "remaining_percent": 100.0 - used,
        "used_percent": used,
        "reported": True,
        "reset_at": reset_at.isoformat().replace("+00:00", "Z"),
        "window_seconds": 604_800,
    }
    return {"label": label, "email": label, "enabled": True, "auth_valid": True, "stale": False, "weekly": window}


def _sample(at: datetime, used: dict[str, float], reset_at: datetime) -> JsonObject:
    accounts: JsonObject = {}
    for label, value in used.items():
        accounts[label] = {"weekly_used_percent": value, "weekly_reset_at": reset_at.isoformat().replace("+00:00", "Z")}
    return {"at": at.isoformat().replace("+00:00", "Z"), "accounts": accounts}


def test_burn_factor_combines_native_burn_with_horizon_capacity_and_subscription_ends() -> None:
    """Prove the end-to-end factor from samples, snapshot accounts and subscription evidence."""
    reset_at = NOW + timedelta(days=2)
    snapshot: JsonObject = {
        "summary": {"capacity_basis": {"key": "weekly", "label": "Weekly"}},
        "accounts": [_account("a@pitchai.net", 40.0, reset_at), _account("b@pitchai.net", 70.0, reset_at)],
    }
    minutes = range(0, 35, 5)
    samples = [
        _sample(
            NOW - timedelta(minutes=30 - minute),
            {"a@pitchai.net": 39.0 + minute / 5, "b@pitchai.net": 70.0},
            reset_at,
        )
        for minute in minutes
    ]
    subscriptions: JsonObject = {
        "timezone": "Europe/Berlin",
        "accounts": [{"email": "b@pitchai.net", "access_state": "active_until_end", "access_ends_on": "2026-10-05"}],
    }
    payload = build_burn_factors(snapshot, samples, parse_pairs("30m:24h"), subscriptions=subscriptions, now=NOW)
    results = payload.get("results")
    first: JsonValue = results[0] if isinstance(results, list) and results else None
    result = require_object(first, description="burn factor result")
    burn = optional_object(result.get("burn"))
    capacity = optional_object(result.get("capacity"))
    check_close(burn.get("points_per_hour"), 12.0, "6 points in 30 minutes")
    check_close(result.get("demand_points"), 288.0, "12 per hour for 24 hours")
    check_equal(capacity.get("subscription_end_count"), 1, "b ends at local midnight inside the horizon")
    check_equal(result.get("status"), "short", "demand far above capacity")
    check_close(result.get("factor"), 288.0 / 90.0, "a 60 left + b 30 burned before its end = 90")
