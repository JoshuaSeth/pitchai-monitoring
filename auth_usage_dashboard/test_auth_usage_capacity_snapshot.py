# Copyright (c) 2026 PitchAI. All rights reserved.
"""Snapshot-level proof for legacy capacity forecasts, warnings, and redaction."""

from __future__ import annotations

import json
from datetime import timedelta

from ._broker_account_test_fixtures import (
    LEAK_MARKER,
    NOW,
    keep_only_weekly_window,
    member,
    objects,
    raw_account,
    snapshot_of,
)
from ._timeseries_test_fixtures import check, check_equal

HALF_CAPACITY_PERCENT = 50
LEAKED_FRAGMENTS = (
    LEAK_MARKER,
    "auth_json",
    "access_token",
    "refresh_token",
    "broker_secret",
    "id-operator@example.com",
)


def test_forecast_counts_current_headroom_and_resets_inside_horizon() -> None:
    """Prove the hour forecast adds current headroom and resets due inside it."""
    available = raw_account(
        "available@example.com",
        five_used=40,
        five_reset=NOW + timedelta(hours=3),
    )
    limited = raw_account(
        "limited@example.com",
        availability="rate_limited",
        five_used=100,
        five_reset=NOW + timedelta(minutes=30),
    )

    snapshot = snapshot_of([available, limited])
    forecasts = objects(snapshot["forecasts"], "forecasts")
    hour = next(item for item in forecasts if item["key"] == "hour")

    check_equal(member(snapshot, "summary")["usable_now"], 1, "usable accounts now")
    check_equal(hour["capacity_points"], 160, "hour capacity points")
    check_equal(hour["account_equivalents"], 1.6, "hour account equivalents")
    check_equal(hour["maximum_points"], 300, "hour maximum points")
    check_equal(hour["capacity_percent"], 53.3, "hour capacity percent")
    check_equal(hour["five_hour_resets"], 1, "five-hour resets inside the hour")
    check_equal(hour["contributing_accounts"], 2, "accounts contributing to the hour")


def test_missing_five_hour_windows_are_unavailable_not_zero_capacity() -> None:
    """Prove absent five-hour windows are unavailable and weekly becomes the basis."""
    accounts = [
        raw_account("a@example.com", weekly_used=0),
        raw_account("b@example.com", weekly_used=100),
    ]
    for raw in accounts:
        keep_only_weekly_window(raw)

    snapshot = snapshot_of(accounts)

    summary = member(snapshot, "summary")
    aggregates = member(summary, "window_aggregates")
    check_equal(
        aggregates["five_hour"],
        {
            "measurement_status": "unavailable",
            "reporting_accounts": 0,
            "unknown_accounts": 2,
            "remaining_points": None,
            "maximum_known_points": None,
            "remaining_percent": None,
        },
        "five-hour aggregate",
    )
    check_equal(member(aggregates, "weekly")["remaining_percent"], 50, "weekly aggregate headroom")
    check_equal(
        summary["capacity_basis"],
        {
            "key": "weekly",
            "label": "Weekly",
            "reporting_accounts": 2,
            "eligible_accounts": 2,
            "measurement_status": "complete",
        },
        "capacity basis",
    )
    forecasts = objects(snapshot["forecasts"], "forecasts")
    complete = all(item["measurement_status"] == "complete" for item in forecasts)
    weekly_basis = all(item["basis_key"] == "weekly" for item in forecasts)
    half_capacity = all(item["capacity_percent"] == HALF_CAPACITY_PERCENT for item in forecasts)
    check(complete, "every forecast is completely measured")
    check(weekly_basis, "every forecast uses the weekly basis")
    check(half_capacity, "every forecast reports half capacity")
    runout = member(snapshot, "runout_forecast")
    check(runout["data_available"] is True, "run-out forecast has data")
    check_equal(member(runout, "capacity_basis")["key"], "weekly", "run-out forecast basis")
    events = objects(snapshot["events"], "events")
    weekly_events = all(item["kind"] == "weekly_reset" for item in events)
    check_equal(len(events), 2, "scheduled events")
    check(weekly_events, "every scheduled event is a weekly reset")
    check_equal(summary["next_useful_capacity_label"], "b@example.com", "next useful capacity")
    warnings = objects(snapshot["warnings"], "warnings")
    unreported_warning = any(item["code"] == "five_hour_unreported" for item in warnings)
    check(unreported_warning, "five-hour unreported warning is raised")


def test_stale_available_account_is_not_counted_as_usable_capacity() -> None:
    """Prove a stale available account contributes no usable capacity."""
    stale = raw_account("stale@example.com", last_probe=NOW - timedelta(minutes=20))

    snapshot = snapshot_of([stale])

    account = objects(snapshot["accounts"], "accounts")[0]
    check_equal(account["status"], "available", "stale account status")
    check(account["stale"] is True, "stale account is marked stale")
    check_equal(member(snapshot, "summary")["usable_now"], 0, "usable accounts now")
    warnings = objects(snapshot["warnings"], "warnings")
    forecasts = objects(snapshot["forecasts"], "forecasts")
    stale_warning = any(item["code"] == "stale" for item in warnings)
    no_points = all(item["capacity_points"] is None for item in forecasts)
    unavailable = all(item["measurement_status"] == "unavailable" for item in forecasts)
    check(stale_warning, "stale warning is raised")
    check(no_points, "no forecast claims capacity points")
    check(unavailable, "every forecast is unavailable")


def test_dashboard_snapshot_does_not_expose_raw_auth_or_broker_identifiers() -> None:
    """Prove the snapshot never serializes auth material or broker identifiers."""
    snapshot = snapshot_of([raw_account("operator@example.com")])
    encoded = json.dumps(snapshot, sort_keys=True)

    for fragment in LEAKED_FRAGMENTS:
        check(fragment not in encoded, f"snapshot must not contain {fragment!r}")
