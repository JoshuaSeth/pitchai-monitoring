# Copyright (c) 2026 PitchAI. All rights reserved.
"""Account-level proof for the legacy Codex capacity parser."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING

from ._broker_account_test_fixtures import (
    LEAK_MARKER,
    NOW,
    keep_only_weekly_window,
    member,
    objects,
    parse_raw,
    raw_account,
)
from ._timeseries_test_fixtures import check, check_equal

if TYPE_CHECKING:
    from .timeseries_types import JsonObject

UNREPORTED_WINDOW: JsonObject = {
    "reported": False,
    "used_percent": None,
    "remaining_percent": None,
    "reset_at": None,
    "reset_in_seconds": None,
    "window_seconds": None,
}


def _check_status(raw: JsonObject, status: str, *, selectable: bool) -> None:
    account = parse_raw(raw)
    check_equal(account["status"], status, "classified account status")
    check(account["selectable_now"] is selectable, f"{status} account selectable_now must be {selectable}")


def test_available_account_is_selectable() -> None:
    """Prove an available account with five-hour headroom is selectable."""
    raw = raw_account("available@example.com")
    _check_status(raw, "available", selectable=True)


def test_disabled_account_is_not_selectable() -> None:
    """Prove a disabled broker account is classified as disabled."""
    raw = raw_account("disabled@example.com", enabled=False)
    _check_status(raw, "disabled", selectable=False)


def test_auth_invalid_account_is_not_selectable() -> None:
    """Prove a broker account with invalid authentication is never selectable."""
    raw = raw_account("invalid@example.com", availability="auth_invalid")
    _check_status(raw, "auth_invalid", selectable=False)


def test_exhausted_weekly_window_is_weekly_limited() -> None:
    """Prove a rate-limited account with a full weekly window is weekly limited."""
    raw = raw_account("weekly@example.com", availability="rate_limited", weekly_used=100)
    _check_status(raw, "weekly_limited", selectable=False)


def test_exhausted_five_hour_window_is_five_hour_limited() -> None:
    """Prove a rate-limited account with a full five-hour window is five-hour limited."""
    raw = raw_account("five@example.com", availability="rate_limited", five_used=100)
    _check_status(raw, "five_hour_limited", selectable=False)


def test_five_hour_headroom_below_floor_is_five_hour_limited() -> None:
    """Prove an available account below the five-hour floor is not selectable."""
    raw = raw_account("floor@example.com", availability="available", five_used=90)
    _check_status(raw, "five_hour_limited", selectable=False)


def test_routing_preference_is_exposed_without_broker_secrets() -> None:
    """Prove the routing preference is exposed while broker secrets are dropped."""
    account = parse_raw(raw_account("preferred@example.com", routing_preferred=True))

    check(account["routing_preferred"] is True, "routing preference is exposed")
    serialized = json.dumps(account)
    check("broker_secret" not in serialized, "broker secret key is dropped")
    check(LEAK_MARKER not in serialized, "secret values are dropped")


def test_expired_provider_reset_is_unknown_until_fresh_probe() -> None:
    """Prove an elapsed provider reset is unknown until a fresh probe arrives."""
    raw = raw_account(
        "expired@example.com",
        availability="rate_limited",
        five_used=100,
        five_reset=NOW - timedelta(seconds=1),
    )

    account = parse_raw(raw)

    check_equal(account["status"], "unknown", "expired reset status")
    check_equal(
        account["status_reason"],
        "Reset is due; awaiting a fresh provider state",
        "expired reset reason",
    )


def test_single_weekly_primary_window_is_not_mislabeled_as_five_hour() -> None:
    """Prove a lone weekly window in the primary slot stays weekly."""
    raw = raw_account("weekly-only@example.com", weekly_used=0)
    keep_only_weekly_window(raw)

    account = parse_raw(raw)

    five_hour = member(account, "five_hour")
    weekly = member(account, "weekly")
    check_equal(account["status"], "available", "weekly-only status")
    check(five_hour["reported"] is False, "five-hour window is unreported")
    check(five_hour["remaining_percent"] is None, "five-hour headroom is unknown")
    check(five_hour["window_seconds"] is None, "five-hour duration is unknown")
    check(weekly["reported"] is True, "weekly window is reported")
    check_equal(weekly["remaining_percent"], 100, "weekly headroom")


def test_windows_are_classified_by_duration_when_provider_order_is_reversed() -> None:
    """Prove windows are matched by duration, not by provider slot order."""
    raw = raw_account("reversed@example.com", five_used=25, weekly_used=40)
    rate_limit = member(raw, "state", "usage", "rate_limit")
    rate_limit["primary_window"], rate_limit["secondary_window"] = (
        rate_limit["secondary_window"],
        rate_limit["primary_window"],
    )

    account = parse_raw(raw)

    check_equal(member(account, "five_hour")["remaining_percent"], 75, "five-hour headroom")
    check_equal(member(account, "weekly")["remaining_percent"], 60, "weekly headroom")


def test_durationless_provider_window_is_unknown_not_five_hour_capacity() -> None:
    """Prove a window without a duration is unknown rather than five-hour capacity."""
    raw = raw_account("durationless@example.com", five_used=100, weekly_used=None)
    member(raw, "state", "usage")["rate_limit"] = {
        "primary_window": {
            "used_percent": 100,
            "reset_at": (NOW + timedelta(hours=2)).isoformat(),
        },
    }

    account = parse_raw(raw)

    check_equal(account["status"], "available", "durationless status")
    check(account["selectable_now"] is True, "durationless account stays selectable")
    check_equal(account["five_hour"], UNREPORTED_WINDOW, "five-hour window is entirely unknown")
    check(member(account, "weekly")["reported"] is False, "weekly window is unreported")


def test_reset_credit_details_support_provider_field_names_and_dates() -> None:
    """Prove camel-case provider reset-credit fields and dates are normalized."""
    raw = raw_account(
        "credits@example.com",
        credits={
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

    reset_credits = member(parse_raw(raw), "reset_credits")

    check_equal(reset_credits["available_count"], 1, "available reset credits")
    check(reset_credits["dates_available"] is True, "reset credit dates are available")
    detail = objects(reset_credits["details"], "reset credit details")[0]
    check_equal(detail["reset_type"], "primary", "reset credit type")
    check_equal(detail["granted_at"], "2026-07-10T08:00:00Z", "reset credit grant date")
    check_equal(detail["expires_at"], "2026-07-12T08:00:00Z", "reset credit expiry date")
