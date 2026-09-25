# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock dashboard forecast capacity and sanitization behavior."""

from __future__ import annotations

import json
import math
from datetime import timedelta

from auth_usage_dashboard.capacity import build_dashboard_snapshot
from domain_checks.testing import verify
from tests.auth_test_contract import required_number
from tests.auth_usage_capacity_support import (
    NOW,
    account_fixture,
    nested_object,
)

EXPECTED_HOUR_CAPACITY_POINTS = 160
EXPECTED_HOUR_MAXIMUM_POINTS = 300
EXPECTED_CONTRIBUTING_ACCOUNTS = 2
EXPECTED_WEEKLY_REMAINING_PERCENT = 50
EXPECTED_WEEKLY_EVENT_COUNT = 2
EXPECTED_ACCOUNT_EQUIVALENTS = 1.6
EXPECTED_CAPACITY_PERCENT = 53.3


def test_forecast_counts_current_headroom_and_resets_inside_horizon() -> None:
    """Verify the behavior described by this test."""
    available = account_fixture(
        "available@example.com",
        five_used=40,
        five_reset=NOW + timedelta(hours=3),
    )
    limited = account_fixture(
        "limited@example.com",
        availability="rate_limited",
        five_used=100,
        five_reset=NOW + timedelta(minutes=30),
    )

    snapshot = build_dashboard_snapshot(
        [available, limited],
        now=NOW,
        stale_after_seconds=600,
        min_five_hour_remaining_percent=10,
    )
    hour = next(item for item in snapshot["forecasts"] if item["key"] == "hour")

    verify(snapshot["summary"]["usable_now"] == 1)
    verify(hour["capacity_points"] == EXPECTED_HOUR_CAPACITY_POINTS)
    verify(
        math.isclose(
            required_number(
                hour["account_equivalents"],
                label="forecast account equivalents",
            ),
            EXPECTED_ACCOUNT_EQUIVALENTS,
        ),
    )
    verify(hour["maximum_points"] == EXPECTED_HOUR_MAXIMUM_POINTS)
    verify(
        math.isclose(
            required_number(
                hour["capacity_percent"],
                label="forecast capacity percent",
            ),
            EXPECTED_CAPACITY_PERCENT,
        ),
    )
    verify(hour["five_hour_resets"] == 1)
    verify(hour["contributing_accounts"] == EXPECTED_CONTRIBUTING_ACCOUNTS)


def test_missing_five_hour_windows_are_unavailable_not_zero_capacity() -> None:
    """Verify the behavior described by this test."""
    accounts = [
        account_fixture("a@example.com", weekly_used=0),
        account_fixture("b@example.com", weekly_used=100),
    ]
    for raw in accounts:
        rate_limit = nested_object(raw, "state", "usage", "rate_limit")
        rate_limit["primary_window"] = rate_limit.pop("secondary_window")

    snapshot = build_dashboard_snapshot(
        accounts,
        now=NOW,
        stale_after_seconds=600,
        min_five_hour_remaining_percent=10,
    )

    verify(
        snapshot["summary"]["window_aggregates"]["five_hour"]
        == {
            "measurement_status": "unavailable",
            "reporting_accounts": 0,
            "unknown_accounts": 2,
            "remaining_points": None,
            "maximum_known_points": None,
            "remaining_percent": None,
        },
    )
    verify(
        snapshot["summary"]["window_aggregates"]["weekly"]["remaining_percent"]
        == EXPECTED_WEEKLY_REMAINING_PERCENT,
    )
    verify(
        snapshot["summary"]["capacity_basis"]
        == {
            "key": "weekly",
            "label": "Weekly",
            "reporting_accounts": 2,
            "eligible_accounts": 2,
            "measurement_status": "complete",
        },
    )
    complete_forecasts = (
        item["measurement_status"] == "complete"
        for item in snapshot["forecasts"]
    )
    weekly_forecasts = (
        item["basis_key"] == "weekly" for item in snapshot["forecasts"]
    )
    expected_capacities = (
        item["capacity_percent"] == EXPECTED_WEEKLY_REMAINING_PERCENT
        for item in snapshot["forecasts"]
    )
    verify(all(complete_forecasts))
    verify(all(weekly_forecasts))
    verify(all(expected_capacities))
    verify(snapshot["runout_forecast"]["data_available"] is True)
    verify(snapshot["runout_forecast"]["capacity_basis"]["key"] == "weekly")
    verify(len(snapshot["events"]) == EXPECTED_WEEKLY_EVENT_COUNT)
    weekly_events = (
        item["kind"] == "weekly_reset" for item in snapshot["events"]
    )
    verify(all(weekly_events))
    verify(snapshot["summary"]["next_useful_capacity_label"] == "b@example.com")
    warning_codes = (item["code"] for item in snapshot["warnings"])
    verify("five_hour_unreported" in warning_codes)


def test_stale_available_account_is_not_counted_as_usable_capacity() -> None:
    """Verify the behavior described by this test."""
    stale = account_fixture(
        "stale@example.com",
        last_probe=NOW - timedelta(minutes=20),
    )

    snapshot = build_dashboard_snapshot(
        [stale],
        now=NOW,
        stale_after_seconds=600,
        min_five_hour_remaining_percent=10,
    )

    verify(snapshot["accounts"][0]["status"] == "available")
    verify(snapshot["accounts"][0]["stale"] is True)
    verify(snapshot["summary"]["usable_now"] == 0)
    stale_warning_codes = (item["code"] for item in snapshot["warnings"])
    unavailable_capacities = (
        item["capacity_points"] is None for item in snapshot["forecasts"]
    )
    unavailable_statuses = (
        item["measurement_status"] == "unavailable"
        for item in snapshot["forecasts"]
    )
    verify("stale" in stale_warning_codes)
    verify(all(unavailable_capacities))
    verify(all(unavailable_statuses))


def test_dashboard_snapshot_does_not_expose_raw_auth_or_broker_identifiers() -> None:
    """Verify the behavior described by this test."""
    snapshot = build_dashboard_snapshot(
        [account_fixture("operator@example.com")],
        now=NOW,
        stale_after_seconds=600,
        min_five_hour_remaining_percent=10,
    )
    encoded = json.dumps(snapshot, sort_keys=True)

    verify("must-not-escape" not in encoded)
    verify("auth_json" not in encoded)
    verify("access_token" not in encoded)
    verify("refresh_token" not in encoded)
    verify("broker_secret" not in encoded)
    verify("id-operator@example.com" not in encoded)
