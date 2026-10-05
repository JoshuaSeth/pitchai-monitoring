# Copyright (c) 2026 PitchAI. All rights reserved.
"""Burn-factor result shaping: factor, status and the capacity breakdown of one pair."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from .timeseries_types import number_value

if TYPE_CHECKING:
    from .burn_factor_capacity import HorizonCapacity
    from .burn_factor_windows import WindowPair
    from .timeseries_types import JsonObject

GOOD_BELOW, SHORT_FROM = 0.85, 1.0
_SECONDS_PER_HOUR = 3600.0


class Counts(NamedTuple):
    """Account counts and the earliest unblock moment reported with every result."""

    eligible: int
    unknown: int
    saturated: int
    credited: int
    ended: int
    blocked: int
    unblocked_at: str | None


def _status(factor: float | None, *, demand: float, limited: bool, known: int) -> str:
    if factor is None:
        return "short" if demand > 0 or known > 0 else "unknown"
    if factor >= SHORT_FROM:
        return "short"
    if limited:
        return "limited"
    return "good" if factor < GOOD_BELOW else "tight"


def pair_result(
    pair: WindowPair,
    burn: JsonObject,
    capacity: HorizonCapacity,
    counts: Counts,
) -> JsonObject:
    """Return one pair's factor, status, runway, margin and capacity breakdown.

    Returns:
        The JSON result for one rolling/horizon pair.
    """
    eligible, unknown, saturated, credited, ended = (
        counts.eligible,
        counts.unknown,
        counts.saturated,
        counts.credited,
        counts.ended,
    )
    rate = number_value(burn.get("points_per_hour")) or 0.0
    demand = rate * pair.horizon_seconds / _SECONDS_PER_HOUR
    effective = capacity.effective_points
    factor = demand / effective if effective > 0 else None
    capacity_payload: JsonObject = {
        "left_now_points": round(capacity.left_now_points, 2),
        "reset_points": round(capacity.reset_points, 2),
        "reset_count": capacity.reset_count,
        "expiring_points": round(capacity.losses.at_resets, 2),
        "subscription_expiring_points": round(capacity.losses.at_subscription_ends, 2),
        "subscription_end_count": capacity.losses.subscription_end_count,
        "ended_subscription_accounts": ended,
        "effective_points": round(effective, 2),
        "eligible_accounts": eligible,
        "unknown_accounts": unknown,
        "saturated_accounts": saturated,
        "credit_accounts": credited,
        "blocked_accounts": counts.blocked,
        "blocked_until": counts.unblocked_at,
        "blocked_points": round(capacity.losses.blocked_at_horizon_end, 2),
    }
    burn_payload: JsonObject = {**burn, "points_per_hour": round(rate, 3)}
    return {
        "rolling": pair.rolling,
        "rolling_seconds": pair.rolling_seconds,
        "horizon": pair.horizon,
        "horizon_seconds": pair.horizon_seconds,
        "factor": round(factor, 3) if factor is not None else None,
        "status": _status(
            factor,
            demand=demand,
            limited=(saturated + counts.blocked) * 2 >= max(1, eligible - unknown - ended),
            known=eligible - unknown - ended,
        ),
        "lower_bound": saturated + counts.blocked > 0,
        "runway_hours": round(capacity.runway_hours, 1) if capacity.runway_hours is not None else None,
        "margin_points": round(effective - demand, 2),
        "demand_points": round(demand, 2),
        "burn": burn_payload,
        "capacity": capacity_payload,
    }
