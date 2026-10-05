# Copyright (c) 2026 PitchAI. All rights reserved.
"""Daily-total-constrained hourly token allocation with three-hour smoothing."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .history_values import isoformat

if TYPE_CHECKING:
    from datetime import date

    from .timeseries_types import JsonObject, JsonValue

type HourTokens = tuple[int, int]

_HOURS_PER_DAY = 24
_SMOOTHING_OFFSETS = range(-2, 3)
_SMOOTHING_WEIGHTS = (1, 2, 3, 2, 1)


def hourly_allocations(
    hours: list[datetime],
    *,
    daily_totals: dict[str, int],
    observed: dict[datetime, int],
    now: datetime,
) -> list[HourTokens]:
    """Spread provider daily totals over hours, preferring observed deltas.

    Returns:
        One ``(tokens, observed_tokens)`` pair per requested hour.
    """
    allocations: dict[datetime, HourTokens] = {}
    dates = sorted({hour.date() for hour in hours})
    for day in dates:
        total = daily_totals.get(day.isoformat(), 0)
        if total > 0:
            allocations.update(_day_allocations(day, total=total, observed=observed, now=now))
    return [allocations.get(hour, (0, 0)) for hour in hours]


def hour_points(
    hours: list[datetime],
    allocations: list[HourTokens],
    *,
    extra: JsonObject,
) -> list[JsonValue]:
    """Render hourly allocations as smoothed JSON points.

    Returns:
        One point per hour with ``extra`` fields placed before the smoothed value.
    """
    token_values = [tokens for tokens, _observed_tokens in allocations]
    smoothed = _smoothed_values(token_values)
    points: list[JsonValue] = []
    for at, (tokens, observed_tokens), smoothed_tokens in zip(hours, allocations, smoothed, strict=True):
        points.append({
            "at": isoformat(at),
            "tokens": tokens,
            "observed_tokens": observed_tokens,
            "reconstructed_tokens": max(0, tokens - observed_tokens),
            "provenance": _provenance(tokens, observed_tokens),
            **extra,
            "smoothed_tokens": smoothed_tokens,
        })
    return points


def _day_allocations(
    day: date,
    *,
    total: int,
    observed: dict[datetime, int],
    now: datetime,
) -> dict[datetime, HourTokens]:
    active_count = _HOURS_PER_DAY if day < now.date() else now.hour + 1
    hour_numbers = range(active_count)
    active_hours = [datetime(day.year, day.month, day.day, hour, tzinfo=UTC) for hour in hour_numbers]
    observed_values = _bounded_observed(
        _observed_on_day(observed, day=day, active_hours=active_hours),
        total=total,
    )
    observed_total = sum(observed_values.values())
    reconstructed = _distribute_integer(total - observed_total, active_hours)
    return {
        hour: (
            reconstructed.get(hour, 0) + observed_values.get(hour, 0),
            observed_values.get(hour, 0),
        )
        for hour in active_hours
    }


def _observed_on_day(
    observed: dict[datetime, int],
    *,
    day: date,
    active_hours: list[datetime],
) -> dict[datetime, int]:
    observed_items = observed.items()
    return {hour: value for hour, value in observed_items if hour.date() == day and hour in active_hours and value > 0}


def _bounded_observed(values: dict[datetime, int], *, total: int) -> dict[datetime, int]:
    observed_total = sum(values.values())
    if observed_total <= total:
        return values
    if observed_total <= 0:
        return {}
    value_items = values.items()
    weights = {hour: value / observed_total for hour, value in value_items}
    return _distribute_weighted(total, weights)


def _distribute_integer(total: int, keys: list[datetime]) -> dict[datetime, int]:
    if total <= 0 or not keys:
        return dict.fromkeys(keys, 0)
    base, remainder = divmod(total, len(keys))
    return {key: base + (1 if index < remainder else 0) for index, key in enumerate(keys)}


def _distribute_weighted(total: int, weights: dict[datetime, float]) -> dict[datetime, int]:
    weight_items = weights.items()
    raw = {key: total * weight for key, weight in weight_items}
    raw_items = raw.items()
    result = {key: math.floor(value) for key, value in raw_items}
    remainder = total - sum(result.values())
    order = sorted(raw, key=lambda key: raw[key] - result[key], reverse=True)
    for key in order[:remainder]:
        result[key] += 1
    return result


def _smoothed_values(values: list[int]) -> list[int]:
    numbers = [float(value) for value in values]
    smoothed: list[int] = []
    for index in range(len(numbers)):
        weighted = 0.0
        divisor = 0
        for offset, weight in zip(_SMOOTHING_OFFSETS, _SMOOTHING_WEIGHTS, strict=True):
            candidate = index + offset
            if 0 <= candidate < len(numbers):
                weighted += numbers[candidate] * weight
                divisor += weight
        smoothed.append(round(weighted / divisor) if divisor else 0)
    return smoothed


def _provenance(tokens: int, observed_tokens: int) -> str:
    if observed_tokens <= 0:
        return "reconstructed" if tokens > 0 else "none"
    return "observed" if observed_tokens >= tokens else "blended"
