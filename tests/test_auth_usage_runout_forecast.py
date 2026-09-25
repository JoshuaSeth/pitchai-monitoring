# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock dashboard runout forecast boundary behavior."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from auth_usage_dashboard.history import capacity_burn_rate
from auth_usage_dashboard.runout import build_runout_forecast, first_runout
from domain_checks.testing import verify
from tests.auth_test_contract import required_number
from tests.auth_usage_history_support import (
    NOW,
    account_fixture,
    reset_bank_fixture,
    sample_fixture,
)

if TYPE_CHECKING:
    from auth_usage_dashboard.models import CapacityScheduleEvent, UsageSample

EXPECTED_BANKED_RESET_COUNT = 99
EXPECTED_WEEKLY_CAPACITY_POINTS = 80
EXPECTED_CAPACITY_POINTS_PER_HOUR = 10


def test_first_runout_accounts_for_reset_arrival_without_redeeming_bank() -> None:
    """Account for scheduled reset arrival without treating bank as capacity."""
    reset_at = NOW + timedelta(minutes=30)
    first_events: list[CapacityScheduleEvent] = [
        {
            "at": reset_at,
            "account_label": "operator@example.com",
            "capacity_points": 100.0,
        },
    ]
    no_outage = first_runout(
        {"operator@example.com": 10.0},
        first_events,
        now=NOW,
        horizon_end=NOW + timedelta(hours=1),
        burn_rate_per_hour=20.0,
    )
    second_events: list[CapacityScheduleEvent] = [
        {
            "at": reset_at + timedelta(minutes=1),
            "account_label": "operator@example.com",
            "capacity_points": 100.0,
        },
    ]
    outage = first_runout(
        {"operator@example.com": 10.0},
        second_events,
        now=NOW,
        horizon_end=NOW + timedelta(hours=1),
        burn_rate_per_hour=20.0,
    )

    verify(no_outage is None)
    verify(outage == NOW + timedelta(minutes=30))


def test_runout_forecast_excludes_banked_resets_from_capacity() -> None:
    """Exclude manually redeemed banked resets from automatic capacity."""
    samples = [
        sample_fixture(NOW - timedelta(hours=2), 10),
        sample_fixture(NOW - timedelta(hours=1), 50),
        sample_fixture(NOW, 90),
    ]
    account = account_fixture(
        remaining=10,
        used=90,
        reset_at=NOW + timedelta(hours=4),
    )

    without_bank = build_runout_forecast(
        [account],
        samples=samples,
        reset_bank=reset_bank_fixture(0),
        now=NOW,
    )
    with_bank = build_runout_forecast(
        [account],
        samples=samples,
        reset_bank=reset_bank_fixture(EXPECTED_BANKED_RESET_COUNT),
        now=NOW,
    )

    verify(with_bank["horizons"] == without_bank["horizons"])
    verify(with_bank["banked_reset_policy"]["included_as_automatic_capacity"] is False)
    verify(
        with_bank["banked_reset_policy"]["available_count"]
        == EXPECTED_BANKED_RESET_COUNT,
    )
    probability = required_number(
        with_bank["horizons"][0]["probability_percent"],
        label="runout probability percent",
    )
    verify(probability > 0)


def test_runout_forecast_does_not_infer_zero_from_unreported_five_hour_window() -> None:
    """Use weekly capacity when a five-hour window is unreported."""
    account = account_fixture()
    account["five_hour"] = {
        "reported": False,
        "used_percent": None,
        "remaining_percent": None,
        "reset_at": None,
        "reset_in_seconds": None,
        "window_seconds": None,
    }

    forecast = build_runout_forecast(
        [account],
        samples=[],
        reset_bank=reset_bank_fixture(3),
        now=NOW,
    )

    verify(forecast["data_available"] is True)
    verify(forecast["capacity_basis"]["key"] == "weekly")
    verify(forecast["usable_accounts_now"] == 1)
    verify(forecast["initial_capacity_points"] == EXPECTED_WEEKLY_CAPACITY_POINTS)
    available_probabilities = (
        item["probability_percent"] is not None
        for item in forecast["horizons"]
    )
    verify(all(available_probabilities))
    verify(forecast["banked_reset_policy"]["included_as_automatic_capacity"] is False)


def test_weekly_burn_recovers_legacy_samples_that_were_mislabeled_five_hour() -> None:
    """Recover legacy weekly samples stored in the old five-hour fields."""
    legacy_reset = NOW + timedelta(days=5)
    samples: list[UsageSample] = [
        {
            "at": (NOW - timedelta(hours=2)).isoformat(),
            "accounts": {
                "operator@example.com": {
                    "five_used_percent": 10,
                    "five_reset_at": legacy_reset.isoformat(),
                },
            },
        },
        {
            "at": (NOW - timedelta(hours=1)).isoformat(),
            "accounts": {
                "operator@example.com": {
                    "five_used_percent": 20,
                    "five_reset_at": legacy_reset.isoformat(),
                },
            },
        },
        {
            "at": NOW.isoformat(),
            "accounts": {
                "operator@example.com": {
                    "five_used_percent": 30,
                    "five_reset_at": legacy_reset.isoformat(),
                },
            },
        },
    ]

    burn = capacity_burn_rate(
        [account_fixture()],
        samples=samples,
        now=NOW,
        window_key="weekly",
    )

    verify(burn["source"] == "native_broker_samples")
    verify(burn.get("window_key") == "weekly")
    verify(burn["capacity_points_per_hour"] == EXPECTED_CAPACITY_POINTS_PER_HOUR)
