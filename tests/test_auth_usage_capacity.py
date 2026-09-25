# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock capacity parsing, classification, and provider-window behavior."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from domain_checks.testing import verify
from tests.auth_usage_capacity_support import (
    NOW,
    account_fixture,
    nested_object,
    parse_fixture,
)

if TYPE_CHECKING:
    from auth_usage_dashboard.json_contract import JsonObject

FULLY_AVAILABLE_PERCENT = 100
EXPECTED_FIVE_HOUR_REMAINING_PERCENT = 75
EXPECTED_WEEKLY_REMAINING_PERCENT = 60


@pytest.mark.parametrize(
    ("raw", "status", "selectable"),
    [
        (account_fixture("available@example.com"), "available", True),
        (account_fixture("disabled@example.com", enabled=False), "disabled", False),
        (
            account_fixture("invalid@example.com", availability="auth_invalid"),
            "auth_invalid",
            False,
        ),
        (
            account_fixture(
                "weekly@example.com",
                availability="rate_limited",
                weekly_used=100,
            ),
            "weekly_limited",
            False,
        ),
        (
            account_fixture(
                "five@example.com",
                availability="rate_limited",
                five_used=100,
            ),
            "five_hour_limited",
            False,
        ),
        (
            account_fixture(
                "floor@example.com",
                availability="available",
                five_used=90,
            ),
            "five_hour_limited",
            False,
        ),
    ],
)
def test_account_status_classification(
    raw: JsonObject,
    status: str,
    *,
    selectable: bool,
) -> None:
    """Classify each provider account state without ambiguity."""
    account = parse_fixture(raw)
    verify(account["status"] == status)
    verify(account["selectable_now"] is selectable)


def test_routing_preference_is_exposed_without_broker_secrets() -> None:
    """Expose routing preference while excluding raw broker secrets."""
    account = parse_fixture(
        account_fixture("preferred@example.com", routing_preferred=True),
    )

    verify(account["routing_preferred"] is True)
    serialized = json.dumps(account)
    verify("broker_secret" not in serialized)
    verify("must-not-escape" not in serialized)


def test_expired_provider_reset_is_unknown_until_fresh_probe() -> None:
    """Treat a due reset as unknown until a fresh provider probe confirms it."""
    raw = account_fixture(
        "expired@example.com",
        availability="rate_limited",
        five_used=100,
        five_reset=NOW - timedelta(seconds=1),
    )

    account = parse_fixture(raw)

    verify(account["status"] == "unknown")
    verify(account["status_reason"] == "Reset is due; awaiting a fresh provider state")


def test_single_weekly_primary_window_is_not_mislabeled_as_five_hour() -> None:
    """Classify a lone weekly primary window by duration, not provider position."""
    raw = account_fixture("weekly-only@example.com", weekly_used=0)
    rate_limit = nested_object(raw, "state", "usage", "rate_limit")
    rate_limit["primary_window"] = rate_limit.pop("secondary_window")

    account = parse_fixture(raw)

    verify(account["status"] == "available")
    verify(account["five_hour"]["reported"] is False)
    verify(account["five_hour"]["remaining_percent"] is None)
    verify(account["five_hour"]["window_seconds"] is None)
    verify(account["weekly"]["reported"] is True)
    verify(account["weekly"]["remaining_percent"] == FULLY_AVAILABLE_PERCENT)


def test_windows_are_classified_by_duration_when_provider_order_is_reversed() -> None:
    """Classify reversed provider windows by their declared durations."""
    raw = account_fixture("reversed@example.com", five_used=25, weekly_used=40)
    rate_limit = nested_object(raw, "state", "usage", "rate_limit")
    rate_limit["primary_window"], rate_limit["secondary_window"] = (
        rate_limit["secondary_window"],
        rate_limit["primary_window"],
    )

    account = parse_fixture(raw)

    verify(
        account["five_hour"]["remaining_percent"]
        == EXPECTED_FIVE_HOUR_REMAINING_PERCENT,
    )
    verify(
        account["weekly"]["remaining_percent"]
        == EXPECTED_WEEKLY_REMAINING_PERCENT,
    )


def test_durationless_provider_window_is_unknown_not_five_hour_capacity() -> None:
    """Keep durationless provider windows out of known five-hour capacity."""
    raw = account_fixture(
        "durationless@example.com",
        five_used=100,
        weekly_used=None,
    )
    usage = nested_object(raw, "state", "usage")
    usage["rate_limit"] = {
        "primary_window": {
            "used_percent": 100,
            "reset_at": (NOW + timedelta(hours=2)).isoformat(),
        },
    }

    account = parse_fixture(raw)

    verify(account["status"] == "available")
    verify(account["selectable_now"] is True)
    verify(
        account["five_hour"]
        == {
            "reported": False,
            "used_percent": None,
            "remaining_percent": None,
            "reset_at": None,
            "reset_in_seconds": None,
            "window_seconds": None,
        },
    )
    verify(account["weekly"]["reported"] is False)


def test_reset_credit_details_support_provider_field_names_and_dates() -> None:
    """Normalize provider reset-credit field names and preserve safe dates."""
    raw = account_fixture(
        "credits@example.com",
        reset_credits={
            "availableCount": 1,
            "credits": [
                {
                    "resetType": "primary",
                    "status": "available",
                    "grantedAt": "2026-07-10T08:00:00Z",
                    "expiresAt": "2026-07-12T08:00:00Z",
                    "title": "Five-hour reset",
                },
            ],
        },
    )

    reset_bank = parse_fixture(raw)["reset_credits"]

    verify(reset_bank["available_count"] == 1)
    verify(reset_bank["dates_available"] is True)
    verify(reset_bank["details"][0]["reset_type"] == "primary")
    verify(reset_bank["details"][0]["granted_at"] == "2026-07-10T08:00:00Z")
    verify(reset_bank["details"][0]["expires_at"] == "2026-07-12T08:00:00Z")
