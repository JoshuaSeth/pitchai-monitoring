# Copyright (c) 2026 PitchAI. All rights reserved.
"""Deterministic burn scenarios and earliest-expiry capacity draining."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from statistics import NormalDist
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .runout_schedule import ResetEvent

type DrainStep = tuple[datetime, str | None, float]

SCENARIO_COUNT = 199
_VARIATION_FLOOR = 0.15
_VARIATION_CEILING = 1.5
_DEMAND_TOLERANCE = 1e-9
_HIGH_RISK_PERCENT = 60
_MEDIUM_RISK_PERCENT = 25


def scenario_rates(mean: float, *, variation: float) -> list[float]:
    """Return evenly spaced lognormal quantiles around a mean burn rate.

    Returns:
        ``SCENARIO_COUNT`` burn rates, or a single zero rate without burn.
    """
    if mean <= 0:
        return [0.0]
    cv = min(_VARIATION_CEILING, max(_VARIATION_FLOOR, variation))
    sigma_squared = math.log(1.0 + cv * cv)
    sigma = math.sqrt(sigma_squared)
    mu = math.log(mean) - sigma_squared / 2.0
    normal = NormalDist()
    return [math.exp(mu + sigma * normal.inv_cdf((index + 0.5) / SCENARIO_COUNT)) for index in range(SCENARIO_COUNT)]


def first_runout(
    initial: dict[str, float],
    events: list[ResetEvent],
    *,
    now: datetime,
    horizon_end: datetime,
    burn_rate_per_hour: float,
) -> datetime | None:
    """Drain capacity that expires soonest until demand exceeds supply.

    Returns:
        The first moment capacity runs out, or None when it lasts the horizon.
    """
    capacities = dict(initial)
    expiries = {label: _following_expiry(label, events, after=None, horizon_end=horizon_end) for label in capacities}
    cursor = now
    if sum(capacities.values()) <= 0:
        return now
    for event_at, label, capacity_points in _drain_steps(events, horizon_end=horizon_end):
        hours = max(0.0, (event_at - cursor).total_seconds() / 3600.0)
        demand = burn_rate_per_hour * hours
        available = sum(capacities.values())
        if demand > available + _DEMAND_TOLERANCE:
            if burn_rate_per_hour <= 0:
                return None
            return cursor + timedelta(hours=available / burn_rate_per_hour)
        _consume(capacities, expiries, demand)
        cursor = event_at
        if label is not None:
            capacities[label] = float(capacity_points)
            expiries[label] = _following_expiry(label, events, after=event_at, horizon_end=horizon_end)
        if cursor >= horizon_end:
            break
    return None


def percentile_time(values: list[datetime], percentile: float) -> datetime | None:
    """Return the nearest-rank percentile of sorted timestamps.

    Returns:
        The selected timestamp, or None for an empty list.
    """
    if not values:
        return None
    index = round((len(values) - 1) * percentile)
    return values[max(0, min(len(values) - 1, index))]


def risk_level(probability: int) -> str:
    """Return the risk band of one runout probability percentage."""
    if probability >= _HIGH_RISK_PERCENT:
        return "high"
    if probability >= _MEDIUM_RISK_PERCENT:
        return "medium"
    return "low"


def _drain_steps(events: list[ResetEvent], *, horizon_end: datetime) -> Iterator[DrainStep]:
    for event in events:
        yield min(event["at"], horizon_end), event.get("account_label"), event["capacity_points"]
    yield horizon_end, None, 0.0


def _consume(capacities: dict[str, float], expiries: dict[str, datetime], demand: float) -> None:
    remaining_demand = demand
    never = datetime.max.replace(tzinfo=UTC)
    for label in sorted(capacities, key=lambda item: (expiries.get(item, never), item)):
        if remaining_demand <= 0:
            return
        consumed = min(capacities[label], remaining_demand)
        capacities[label] -= consumed
        remaining_demand -= consumed


def _following_expiry(
    label: str,
    events: list[ResetEvent],
    *,
    after: datetime | None,
    horizon_end: datetime,
) -> datetime:
    for event in events:
        if event["account_label"] == label and (after is None or event["at"] > after):
            return event["at"]
    return horizon_end + timedelta(seconds=1)
