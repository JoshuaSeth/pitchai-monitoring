# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build an explicit unavailable runout forecast."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .runout_policy import banked_reset_policy
from .runout_scenarios import unavailable_horizons
from .value_parsing import isoformat

if TYPE_CHECKING:
    from datetime import datetime

    from .models import CapacityAccount, CapacityBasis, ResetBank, RunoutForecast


def unavailable_forecast(
    accounts: list[CapacityAccount],
    *,
    reset_bank: ResetBank,
    now: datetime,
    capacity_basis: CapacityBasis,
) -> RunoutForecast:
    """State that provider windows cannot support runout probabilities.

    Returns:
        The resulting value.

    """
    usable_now = _usable_count(accounts)
    weekly_blocked = 0
    for account in accounts:
        if account.get("status") == "weekly_limited":
            weekly_blocked += 1
    banked_count = reset_bank["total_available"]
    return {
        "data_available": False,
        "generated_at": isoformat(now),
        "capacity_basis": capacity_basis,
        "burn_rate": {
            "capacity_points_per_hour": None,
            "coefficient_of_variation": None,
            "lookback_hours": 2,
            "source": "unavailable",
            "covered_accounts": 0,
            "confidence": "unavailable",
        },
        "initial_capacity_points": None,
        "usable_accounts_now": usable_now,
        "horizons": unavailable_horizons(),
        "highest_risk": "unknown",
        "highest_probability_percent": None,
        "drivers": _unavailable_drivers(
            usable_now=usable_now,
            weekly_blocked=weekly_blocked,
            banked_count=banked_count,
        ),
        "banked_reset_policy": banked_reset_policy(banked_count),
        "methodology": {
            "model": ("unavailable until at least one provider capacity window is reported"),
            "scenario_count": 0,
            "automatic_resets_included": [],
            "weekly_handling": ("Weekly percentages remain visible whenever the provider reports them."),
            "limitations": ("An unknown provider window is not interpreted as either full or exhausted."),
        },
    }


def _usable_count(accounts: list[CapacityAccount]) -> int:
    count = 0
    for account in accounts:
        if account.get("enabled") and account.get("selectable_now") and not account.get("stale"):
            count += 1
    return count


def _unavailable_drivers(
    *,
    usable_now: int,
    weekly_blocked: int,
    banked_count: int,
) -> list[str]:
    drivers = [
        "Provider capacity windows are not currently reported for auth-valid accounts",
        (f"{usable_now} account{'s are' if usable_now != 1 else ' is'} selectable from broker state"),
    ]
    if weekly_blocked:
        drivers.append(
            f"{weekly_blocked} account{'s are' if weekly_blocked != 1 else ' is'} weekly blocked",
        )
    if banked_count:
        drivers.append(
            f"{banked_count} banked reset{'s are' if banked_count != 1 else ' is'} excluded until manually redeemed",
        )
    return drivers
