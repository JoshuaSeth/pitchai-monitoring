# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared runout forecast wording and the unavailable-forecast payload."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .history_values import isoformat, whole_number

if TYPE_CHECKING:
    from datetime import datetime

    from .timeseries_types import JsonObject, JsonValue

HORIZONS = (
    ("hour", "Next hour", 60 * 60),
    ("six_hours", "Next 6 hours", 6 * 60 * 60),
    ("day", "Next 24 hours", 24 * 60 * 60),
)
_BANKED_RESET_REASON = "Banked resets require an explicit redemption action; this dashboard is read-only."


def constraint_drivers(*, weekly_blocked: int, near_weekly: int, banked_count: int) -> list[str]:
    """Describe weekly blocks, weekly headroom, and banked resets.

    Returns:
        One sentence per non-zero constraint, in display order.
    """
    drivers: list[str] = []
    if weekly_blocked:
        drivers.append(f"{weekly_blocked} account{'s are' if weekly_blocked != 1 else ' is'} weekly blocked")
    if near_weekly:
        drivers.append(
            f"{near_weekly} usable account{'s have' if near_weekly != 1 else ' has'} 15% or less weekly headroom",
        )
    if banked_count:
        drivers.append(
            f"{banked_count} banked reset{'s are' if banked_count != 1 else ' is'} excluded until manually redeemed",
        )
    return drivers


def banked_reset_policy(banked_count: int) -> JsonObject:
    """Return the read-only banked reset policy shown with every forecast."""
    return {
        "available_count": banked_count,
        "included_as_automatic_capacity": False,
        "reason": _BANKED_RESET_REASON,
    }


def unavailable_forecast(
    accounts: list[JsonObject],
    *,
    reset_bank: JsonObject,
    now: datetime,
    capacity_basis: JsonObject,
) -> JsonObject:
    """Return the explicit unknown forecast used when no window is reported.

    Returns:
        A forecast payload whose probabilities and capacity are unknown.
    """
    usable_now = sum(
        1
        for account in accounts
        if account.get("enabled") and account.get("selectable_now") and not account.get("stale")
    )
    weekly_blocked = sum(1 for account in accounts if account.get("status") == "weekly_limited")
    banked_count = whole_number(reset_bank.get("total_available") or 0)
    horizons: list[JsonValue] = [_unknown_horizon(horizon) for horizon in HORIZONS]
    drivers: list[JsonValue] = [
        "Provider capacity windows are not currently reported for auth-valid accounts",
        f"{usable_now} account{'s are' if usable_now != 1 else ' is'} selectable from broker state",
        *constraint_drivers(
            weekly_blocked=weekly_blocked,
            near_weekly=0,
            banked_count=banked_count,
        ),
    ]
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
        "horizons": horizons,
        "highest_risk": "unknown",
        "highest_probability_percent": None,
        "drivers": drivers,
        "banked_reset_policy": banked_reset_policy(banked_count),
        "methodology": {
            "model": "unavailable until at least one provider capacity window is reported",
            "scenario_count": 0,
            "automatic_resets_included": [],
            "weekly_handling": "Weekly percentages remain visible whenever the provider reports them.",
            "limitations": "An unknown provider window is not interpreted as either full or exhausted.",
        },
    }


def _unknown_horizon(horizon: tuple[str, str, int]) -> JsonObject:
    key, label, seconds = horizon
    return {
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
    }
