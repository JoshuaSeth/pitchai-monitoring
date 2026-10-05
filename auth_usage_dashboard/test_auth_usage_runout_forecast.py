# Copyright (c) 2026 PitchAI. All rights reserved.
"""Proof for the legacy run-out forecast and its reset-arrival scheduler."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from ._broker_account_test_fixtures import json_object, member, objects
from ._timeseries_test_fixtures import check, check_equal
from ._usage_history_test_fixtures import NOW, OPERATOR, dashboard_account, trailing_samples
from .runout import build_runout_forecast
from .runout_scenarios import first_runout
from .timeseries_types import number_value

if TYPE_CHECKING:
    from datetime import datetime

    from .runout_schedule import ResetEvent

BURN_POINTS_PER_HOUR = 20.0
INITIAL_POINTS = 10.0
RESET_POINTS = 100.0


def _reset_at(at: datetime) -> list[ResetEvent]:
    """Return a single full five-hour reset for the operator at ``at``.

    Returns:
        One scheduled reset event.
    """
    event: ResetEvent = {"at": at, "account_label": OPERATOR, "capacity_points": RESET_POINTS}
    return [event]


def test_first_runout_accounts_for_reset_arrival_without_redeeming_bank() -> None:
    """Prove a reset arriving exactly at exhaustion prevents the run-out a later one cannot."""
    reset_at = NOW + timedelta(minutes=30)
    horizon_end = NOW + timedelta(hours=1)

    no_outage = first_runout(
        {OPERATOR: INITIAL_POINTS},
        _reset_at(reset_at),
        now=NOW,
        horizon_end=horizon_end,
        burn_rate_per_hour=BURN_POINTS_PER_HOUR,
    )
    outage = first_runout(
        {OPERATOR: INITIAL_POINTS},
        _reset_at(reset_at + timedelta(minutes=1)),
        now=NOW,
        horizon_end=horizon_end,
        burn_rate_per_hour=BURN_POINTS_PER_HOUR,
    )

    check(no_outage is None, "a reset arriving at exhaustion prevents the run-out")
    check_equal(outage, NOW + timedelta(minutes=30), "a late reset leaves a run-out at exhaustion")


def test_runout_forecast_excludes_banked_resets_from_capacity() -> None:
    """Prove banked resets never change the automatic run-out horizons."""
    samples = trailing_samples(10, 50, 90)
    account = dashboard_account(remaining=10, reset_at=NOW + timedelta(hours=4))

    without_bank = json_object(
        build_runout_forecast([account], samples=samples, reset_bank={"total_available": 0}, now=NOW),
    )
    with_bank = json_object(
        build_runout_forecast([account], samples=samples, reset_bank={"total_available": 99}, now=NOW),
    )

    check_equal(with_bank["horizons"], without_bank["horizons"], "banked resets do not change horizons")
    policy = member(with_bank, "banked_reset_policy")
    check(policy["included_as_automatic_capacity"] is False, "banked resets are not automatic capacity")
    check_equal(policy["available_count"], 99, "banked reset count")
    first_horizon = objects(with_bank["horizons"], "horizons")[0]
    probability = number_value(first_horizon["probability_percent"])
    check(probability is not None and probability > 0, "the first horizon carries run-out risk")


def test_runout_forecast_does_not_infer_zero_from_unreported_five_hour_window() -> None:
    """Prove an unreported five-hour window falls back to weekly instead of zero capacity."""
    account = dashboard_account()
    account["five_hour"] = {
        "reported": False,
        "used_percent": None,
        "remaining_percent": None,
        "reset_at": None,
        "window_seconds": None,
    }

    forecast = json_object(
        build_runout_forecast([account], samples=[], reset_bank={"total_available": 3}, now=NOW),
    )

    check(forecast["data_available"] is True, "forecast has data")
    check_equal(member(forecast, "capacity_basis")["key"], "weekly", "forecast basis")
    check_equal(forecast["usable_accounts_now"], 1, "usable accounts now")
    check_equal(forecast["initial_capacity_points"], 80, "initial weekly capacity points")
    horizons = objects(forecast["horizons"], "horizons")
    measured = all(item["probability_percent"] is not None for item in horizons)
    check(measured, "every horizon has a probability")
    policy = member(forecast, "banked_reset_policy")
    check(policy["included_as_automatic_capacity"] is False, "banked resets are not automatic capacity")
