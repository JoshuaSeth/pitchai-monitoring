# Copyright (c) 2026 PitchAI. All rights reserved.
"""Assemble capacity schedules and burn scenarios into a runout forecast."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from .history import capacity_burn_rate
from .runout_basis import measured_accounts, select_capacity_basis, window_label
from .runout_policy import banked_reset_policy
from .runout_scenarios import (
    ScenarioInputs,
    build_horizons,
    highest_horizon,
    scenario_rates,
)
from .runout_schedule import capacity_schedule
from .runout_unavailable import unavailable_forecast
from .value_parsing import UTC, isoformat

_NEAR_WEEKLY_LIMIT_PERCENT = 15

if TYPE_CHECKING:
    from datetime import datetime

    from .models import (
        CapacityAccount,
        CapacityBasis,
        CapacityBurnRate,
        ResetBank,
        RunoutForecast,
        RunoutHorizon,
        UsageSample,
    )


class ForecastStats(NamedTuple):
    """Hold the aggregate capacity facts presented with each forecast."""

    initial_points: float
    usable_now: int
    weekly_blocked: int
    near_weekly: int
    banked_count: int


class ForecastInputs(NamedTuple):
    """Bundle the computed fields used to serialize a runout forecast."""

    now: datetime
    basis: CapacityBasis
    burn: CapacityBurnRate
    rates: list[float]
    stats: ForecastStats
    horizons: list[RunoutHorizon]
    window_key: str


def build_runout_forecast(
    accounts: list[CapacityAccount],
    *,
    samples: list[UsageSample],
    reset_bank: ResetBank,
    now: datetime,
    capacity_basis: CapacityBasis | None = None,
) -> RunoutForecast:
    """Model exhaustion probabilities without treating banked resets as capacity.

    Returns:
        The resulting value.

    """
    now = now.astimezone(UTC)
    basis = capacity_basis or select_capacity_basis(accounts)
    window_key = basis.get("key")
    if window_key not in {"five_hour", "weekly"}:
        return unavailable_forecast(
            accounts,
            reset_bank=reset_bank,
            now=now,
            capacity_basis=basis,
        )
    if not measured_accounts(accounts, window_key=window_key):
        return unavailable_forecast(
            accounts,
            reset_bank=reset_bank,
            now=now,
            capacity_basis=basis,
        )
    burn = capacity_burn_rate(
        accounts,
        samples=samples,
        now=now,
        window_key=window_key,
    )
    base_rate, variation = _required_burn_values(burn)
    rates = scenario_rates(base_rate, variation=variation)
    initial, events = capacity_schedule(
        accounts,
        now=now,
        horizon_seconds=24 * 60 * 60,
        window_key=window_key,
    )
    stats = _forecast_stats(
        accounts,
        initial=initial,
        banked_count=reset_bank["total_available"],
    )
    horizons = build_horizons(ScenarioInputs(initial, events, now, window_key, rates))
    return _available_forecast(
        ForecastInputs(now, basis, burn, rates, stats, horizons, window_key),
    )


def _required_burn_values(burn: CapacityBurnRate) -> tuple[float, float]:
    base_rate = burn["capacity_points_per_hour"]
    variation = burn["coefficient_of_variation"]
    if base_rate is None or variation is None:
        msg = "measured capacity burn rate is missing required values"
        raise RuntimeError(msg)
    return base_rate, variation


def _forecast_stats(
    accounts: list[CapacityAccount],
    *,
    initial: dict[str, float],
    banked_count: int,
) -> ForecastStats:
    weekly_blocked = 0
    near_weekly = 0
    for account in accounts:
        if account.get("status") == "weekly_limited":
            weekly_blocked += 1
        if _near_weekly_limit(account):
            near_weekly += 1
    initial_points = sum(initial.values())
    usable_now = 0
    for value in initial.values():
        if value > 0:
            usable_now += 1
    return ForecastStats(
        initial_points,
        usable_now,
        weekly_blocked,
        near_weekly,
        banked_count,
    )


def _near_weekly_limit(account: CapacityAccount) -> bool:
    remaining = account["weekly"]["remaining_percent"]
    return bool(
        account.get("status") == "available" and remaining is not None and remaining <= _NEAR_WEEKLY_LIMIT_PERCENT,
    )


def _available_forecast(inputs: ForecastInputs) -> RunoutForecast:
    highest = highest_horizon(inputs.horizons)
    return {
        "data_available": True,
        "generated_at": isoformat(inputs.now),
        "capacity_basis": inputs.basis,
        "burn_rate": inputs.burn,
        "initial_capacity_points": round(inputs.stats.initial_points, 1),
        "usable_accounts_now": inputs.stats.usable_now,
        "horizons": inputs.horizons,
        "highest_risk": highest["risk"] if highest else "low",
        "highest_probability_percent": (highest["probability_percent"] if highest else 0),
        "drivers": _drivers(inputs),
        "banked_reset_policy": banked_reset_policy(inputs.stats.banked_count),
        "methodology": {
            "model": ("deterministic lognormal burn scenarios with earliest-expiry capacity scheduling"),
            "scenario_count": len(inputs.rates),
            "automatic_resets_included": [inputs.window_key],
            "weekly_handling": (
                "Weekly exhaustion blocks an account until reset. Weekly percentage "
                "points are used only when weekly is the declared forecast basis."
            ),
            "limitations": (
                "The model assumes the broker consumes capacity that expires soonest "
                "and that the estimated burn distribution remains stable."
            ),
        },
    }


def _drivers(inputs: ForecastInputs) -> list[str]:
    stats = inputs.stats
    drivers = [
        (
            f"{inputs.burn['capacity_points_per_hour']:.1f} "
            f"{window_label(inputs.window_key).lower()} capacity points/hour "
            "at the current burn estimate"
        ),
        (
            f"{stats.usable_now} selectable account"
            f"{'s' if stats.usable_now != 1 else ''} with "
            f"{stats.initial_points:.0f} points now"
        ),
    ]
    if stats.weekly_blocked:
        drivers.append(
            f"{stats.weekly_blocked} account{'s are' if stats.weekly_blocked != 1 else ' is'} weekly blocked",
        )
    if stats.near_weekly:
        drivers.append(
            f"{stats.near_weekly} usable account"
            f"{'s have' if stats.near_weekly != 1 else ' has'} "
            "15% or less weekly headroom",
        )
    if stats.banked_count:
        drivers.append(
            f"{stats.banked_count} banked reset"
            f"{'s are' if stats.banked_count != 1 else ' is'} "
            "excluded until manually redeemed",
        )
    return drivers
