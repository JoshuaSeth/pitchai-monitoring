# Copyright (c) 2026 PitchAI. All rights reserved.
"""Probabilistic capacity runout forecast over the next 24 hours."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import TYPE_CHECKING

from .history_burn import capacity_burn_rate
from .history_values import eligible_accounts, isoformat, real_number, whole_number
from .runout_basis import (
    account_window,
    reports_remaining,
    select_capacity_basis,
    window_label,
)
from .runout_payloads import (
    HORIZONS,
    banked_reset_policy,
    constraint_drivers,
    unavailable_forecast,
)
from .runout_scenarios import SCENARIO_COUNT, percentile_time, risk_level, scenario_rates
from .runout_scenarios import first_runout as _first_runout
from .runout_schedule import capacity_schedule

if TYPE_CHECKING:
    from datetime import datetime

    from .runout_schedule import ResetEvent
    from .timeseries_types import JsonObject, JsonValue

__all__ = [
    "HORIZONS",
    "SCENARIO_COUNT",
    "UTC",
    "build_runout_forecast",
    "select_capacity_basis",
]

_FORECAST_HORIZON_SECONDS = 24 * 60 * 60
_NEAR_WEEKLY_LIMIT_PERCENT = 15
_MODEL = "deterministic lognormal burn scenarios with earliest-expiry capacity scheduling"
_WEEKLY_HANDLING = (
    "Weekly exhaustion blocks an account until reset. Weekly percentage points are used only when weekly "
    "is the declared forecast basis."
)
_LIMITATIONS = (
    "The model assumes the broker consumes capacity that expires soonest and that the estimated burn "
    "distribution remains stable."
)


@dataclass(frozen=True)
class _Scenarios:
    initial: dict[str, float]
    events: list[ResetEvent]
    rates: list[float]
    now: datetime
    window_key: str


def build_runout_forecast(
    accounts: list[JsonObject],
    *,
    samples: list[JsonObject],
    reset_bank: JsonObject,
    now: datetime,
    capacity_basis: JsonObject | None = None,
) -> JsonObject:
    """Forecast the probability that selectable capacity runs out.

    Returns:
        Runout probabilities per horizon with burn evidence and drivers, or an
        explicit unknown forecast when no provider window is reported.
    """
    current = now.astimezone(UTC)
    basis = capacity_basis or select_capacity_basis(accounts)
    window_key = basis.get("key")
    if window_key not in {"five_hour", "weekly"} or not _measured_accounts(accounts, window_key=window_key):
        return unavailable_forecast(accounts, reset_bank=reset_bank, now=current, capacity_basis=basis)
    burn = capacity_burn_rate(accounts, samples=samples, now=current, window_key=window_key)
    rates = scenario_rates(
        real_number(burn["capacity_points_per_hour"]),
        variation=real_number(burn["coefficient_of_variation"]),
    )
    initial, events = capacity_schedule(
        accounts,
        now=current,
        horizon_seconds=_FORECAST_HORIZON_SECONDS,
        window_key=window_key,
    )
    scenarios = _Scenarios(initial=initial, events=events, rates=rates, now=current, window_key=window_key)
    return _forecast_payload(accounts, scenarios, burn=burn, basis=basis, reset_bank=reset_bank)


def _measured_accounts(accounts: list[JsonObject], *, window_key: str) -> list[JsonObject]:
    eligible = eligible_accounts(accounts)
    return [account for account in eligible if reports_remaining(account, window_key)]


def _forecast_payload(
    accounts: list[JsonObject],
    scenarios: _Scenarios,
    *,
    burn: JsonObject,
    basis: JsonObject,
    reset_bank: JsonObject,
) -> JsonObject:
    horizons: list[JsonValue] = []
    probabilities: list[int] = []
    for key, label, seconds in HORIZONS:
        probability, horizon = _horizon(scenarios, key=key, label=label, seconds=seconds)
        probabilities.append(probability)
        horizons.append(horizon)
    highest = max(probabilities, default=None)
    banked_count = whole_number(reset_bank.get("total_available") or 0)
    return {
        "data_available": True,
        "generated_at": isoformat(scenarios.now),
        "capacity_basis": basis,
        "burn_rate": burn,
        "initial_capacity_points": round(sum(scenarios.initial.values()), 1),
        "usable_accounts_now": _usable_now(scenarios),
        "horizons": horizons,
        "highest_risk": risk_level(highest) if highest is not None else "low",
        "highest_probability_percent": highest if highest is not None else 0,
        "drivers": _drivers(accounts, scenarios, burn=burn, banked_count=banked_count),
        "banked_reset_policy": banked_reset_policy(banked_count),
        "methodology": {
            "model": _MODEL,
            "scenario_count": len(scenarios.rates),
            "automatic_resets_included": [scenarios.window_key],
            "weekly_handling": _WEEKLY_HANDLING,
            "limitations": _LIMITATIONS,
        },
    }


def _horizon(scenarios: _Scenarios, *, key: str, label: str, seconds: int) -> tuple[int, JsonObject]:
    end = scenarios.now + timedelta(seconds=seconds)
    relevant_events = [event for event in scenarios.events if event["at"] <= end]
    runout_times = _runout_times(scenarios, relevant_events, horizon_end=end)
    scenario_count = len(scenarios.rates)
    probability = round(len(runout_times) / scenario_count * 100.0) if scenario_count else 0
    resets = sum(1 for event in relevant_events if event["capacity_points"] > 0)
    reset_points = sum(float(event["capacity_points"]) for event in relevant_events)
    return probability, {
        "key": key,
        "label": label,
        "horizon_seconds": seconds,
        "probability_percent": probability,
        "risk": risk_level(probability),
        "expected_runout_at": _optional_isoformat(percentile_time(runout_times, 0.5)),
        "likely_window_start": _optional_isoformat(percentile_time(runout_times, 0.25)),
        "likely_window_end": _optional_isoformat(percentile_time(runout_times, 0.75)),
        "initial_capacity_points": round(sum(scenarios.initial.values()), 1),
        "scheduled_resets": resets,
        "scheduled_five_hour_resets": resets if scenarios.window_key == "five_hour" else 0,
        "scheduled_capacity_points": round(reset_points, 1),
        "scenario_count": scenario_count,
    }


def _runout_times(
    scenarios: _Scenarios,
    events: list[ResetEvent],
    *,
    horizon_end: datetime,
) -> list[datetime]:
    runout_times: list[datetime] = []
    for rate in scenarios.rates:
        runout = _first_runout(
            scenarios.initial,
            events,
            now=scenarios.now,
            horizon_end=horizon_end,
            burn_rate_per_hour=rate,
        )
        if runout is not None:
            runout_times.append(runout)
    runout_times.sort()
    return runout_times


def _usable_now(scenarios: _Scenarios) -> int:
    return sum(1 for points in scenarios.initial.values() if points > 0)


def _drivers(
    accounts: list[JsonObject],
    scenarios: _Scenarios,
    *,
    burn: JsonObject,
    banked_count: int,
) -> list[JsonValue]:
    base_rate = real_number(burn["capacity_points_per_hour"])
    usable_now = _usable_now(scenarios)
    initial_points = sum(scenarios.initial.values())
    weekly_blocked = sum(1 for account in accounts if account.get("status") == "weekly_limited")
    near_weekly = sum(1 for account in accounts if account.get("status") == "available" and _near_weekly_limit(account))
    return [
        (
            f"{base_rate:.1f} {window_label(scenarios.window_key).lower()} capacity points/hour "
            "at the current burn estimate"
        ),
        f"{usable_now} selectable account{'s' if usable_now != 1 else ''} with {initial_points:.0f} points now",
        *constraint_drivers(
            weekly_blocked=weekly_blocked,
            near_weekly=near_weekly,
            banked_count=banked_count,
        ),
    ]


def _near_weekly_limit(account: JsonObject) -> bool:
    remaining = account_window(account, "weekly").get("remaining_percent")
    return isinstance(remaining, (int, float)) and remaining <= _NEAR_WEEKLY_LIMIT_PERCENT


def _optional_isoformat(value: datetime | None) -> str | None:
    return isoformat(value) if value is not None else None
