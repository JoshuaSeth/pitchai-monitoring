# Copyright (c) 2026 PitchAI. All rights reserved.
"""Evaluate deterministic runout scenarios across dashboard horizons."""

from __future__ import annotations

import math
from datetime import timedelta
from statistics import NormalDist
from typing import TYPE_CHECKING, NamedTuple

from .runout_schedule import first_runout
from .value_parsing import optional_isoformat

if TYPE_CHECKING:
    from datetime import datetime

    from .models import CapacityScheduleEvent, RunoutHorizon

HORIZONS = (
    ("hour", "Next hour", 60 * 60),
    ("six_hours", "Next 6 hours", 6 * 60 * 60),
    ("day", "Next 24 hours", 24 * 60 * 60),
)
SCENARIO_COUNT = 199
_HIGH_RISK_PROBABILITY = 60
_MEDIUM_RISK_PROBABILITY = 25


class ScenarioInputs(NamedTuple):
    """Bundle the schedule inputs shared by every horizon."""

    initial: dict[str, float]
    events: list[CapacityScheduleEvent]
    now: datetime
    window_key: str
    rates: list[float]


def scenario_rates(mean: float, *, variation: float) -> list[float]:
    """Create deterministic lognormal burn-rate quantiles.

    Returns:
        The resulting collection.

    """
    if mean <= 0:
        return [0.0]
    coefficient = min(1.5, max(0.15, variation))
    sigma_squared = math.log(1.0 + coefficient * coefficient)
    sigma = math.sqrt(sigma_squared)
    mu = math.log(mean) - sigma_squared / 2.0
    normal = NormalDist()
    rates: list[float] = []
    for index in range(SCENARIO_COUNT):
        quantile = (index + 0.5) / SCENARIO_COUNT
        rates.append(math.exp(mu + sigma * normal.inv_cdf(quantile)))
    return rates


def build_horizons(inputs: ScenarioInputs) -> list[RunoutHorizon]:
    """Evaluate every declared horizon against the same scenarios.

    Returns:
        The resulting collection.

    """
    horizons: list[RunoutHorizon] = []
    for key, label, seconds in HORIZONS:
        horizons.append(_build_horizon(inputs, key=key, label=label, seconds=seconds))
    return horizons


def _build_horizon(
    inputs: ScenarioInputs,
    *,
    key: str,
    label: str,
    seconds: int,
) -> RunoutHorizon:
    end = inputs.now + timedelta(seconds=seconds)
    relevant_events: list[CapacityScheduleEvent] = [event for event in inputs.events if event["at"] <= end]
    runout_times: list[datetime] = []
    for rate in inputs.rates:
        runout = first_runout(
            inputs.initial,
            relevant_events,
            now=inputs.now,
            horizon_end=end,
            burn_rate_per_hour=rate,
        )
        if runout is not None:
            runout_times.append(runout)
    runout_times.sort()
    probability = _probability(runout_times, scenario_count=len(inputs.rates))
    resets = sum(1 for event in relevant_events if event["capacity_points"] > 0)
    reset_points = sum(float(event["capacity_points"]) for event in relevant_events)
    return {
        "key": key,
        "label": label,
        "horizon_seconds": seconds,
        "probability_percent": probability,
        "risk": risk_level(probability),
        "expected_runout_at": optional_isoformat(
            _percentile_time(runout_times, 0.5),
        ),
        "likely_window_start": optional_isoformat(
            _percentile_time(runout_times, 0.25),
        ),
        "likely_window_end": optional_isoformat(
            _percentile_time(runout_times, 0.75),
        ),
        "initial_capacity_points": round(sum(inputs.initial.values()), 1),
        "scheduled_resets": resets,
        "scheduled_five_hour_resets": resets if inputs.window_key == "five_hour" else 0,
        "scheduled_capacity_points": round(reset_points, 1),
        "scenario_count": len(inputs.rates),
    }


def unavailable_horizons() -> list[RunoutHorizon]:
    """Return horizon placeholders when provider windows are unavailable."""
    horizons: list[RunoutHorizon] = []
    for key, label, seconds in HORIZONS:
        horizons.append(
            {
                "key": key,
                "label": label,
                "horizon_seconds": seconds,
                "probability_percent": None,
                "risk": "unknown",
                "expected_runout_at": None,
                "likely_window_start": None,
                "likely_window_end": None,
                "initial_capacity_points": None,
                "scheduled_resets": 0,
                "scheduled_five_hour_resets": 0,
                "scheduled_capacity_points": None,
                "scenario_count": 0,
            },
        )
    return horizons


def highest_horizon(horizons: list[RunoutHorizon]) -> RunoutHorizon | None:
    """Return the horizon with the highest known exhaustion probability."""
    highest: RunoutHorizon | None = None
    highest_probability = -1
    for horizon in horizons:
        probability = horizon["probability_percent"] or 0
        if probability > highest_probability:
            highest = horizon
            highest_probability = probability
    return highest


def _probability(values: list[datetime], *, scenario_count: int) -> int:
    if not scenario_count:
        return 0
    return round(len(values) / scenario_count * 100.0)


def _percentile_time(values: list[datetime], percentile: float) -> datetime | None:
    if not values:
        return None
    index = round((len(values) - 1) * percentile)
    return values[max(0, min(len(values) - 1, index))]


def risk_level(probability: int) -> str:
    """Map a modeled probability to the dashboard risk vocabulary.

    Returns:
        The resulting text.

    """
    if probability >= _HIGH_RISK_PROBABILITY:
        return "high"
    if probability >= _MEDIUM_RISK_PROBABILITY:
        return "medium"
    return "low"
