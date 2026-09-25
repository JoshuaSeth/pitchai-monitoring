# Copyright (c) 2026 PitchAI. All rights reserved.
"""Reconstruct bounded hourly token points from daily and sampled totals."""

from __future__ import annotations

import itertools
import math
from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING

from .value_parsing import UTC, integer, isoformat, parse_datetime

if TYPE_CHECKING:
    from datetime import date

    from .models import HistoryPoint, UsageSample


def floor_hour(value: datetime) -> datetime:
    """Round one timestamp down to its containing UTC hour.

    Returns:
        The resulting value.

    """
    utc_value = value.astimezone(UTC)
    return utc_value.replace(minute=0, second=0, microsecond=0)


def observed_token_deltas(
    samples: list[UsageSample],
    *,
    start: datetime,
    end: datetime,
) -> dict[str, dict[datetime, int]]:
    """Collect positive same-day token deltas from adjacent samples.

    Returns:
        The resulting collection.

    """
    observed: dict[str, dict[datetime, int]] = defaultdict(
        lambda: defaultdict(int),
    )
    ordered = sorted(samples, key=lambda sample: sample.get("at", ""))
    for previous, current in itertools.pairwise(ordered):
        _record_observed_interval(observed, previous, current, start=start, end=end)

    normalized: dict[str, dict[datetime, int]] = {}
    for label, values in observed.items():
        normalized[label] = dict(values)
    return normalized


def _record_observed_interval(
    observed: dict[str, dict[datetime, int]],
    previous: UsageSample,
    current: UsageSample,
    *,
    start: datetime,
    end: datetime,
) -> None:
    current_at = parse_datetime(current.get("at"))
    if current_at is None or current_at < start or current_at > end:
        return
    previous_accounts = previous.get("accounts", {})
    current_accounts = current.get("accounts", {})
    for label, current_account in current_accounts.items():
        previous_account = previous_accounts.get(label)
        if previous_account is None:
            continue
        if previous_account.get("token_date") != current_account.get("token_date"):
            continue
        previous_total = integer(previous_account.get("tokens_today"))
        current_total = integer(current_account.get("tokens_today"))
        if previous_total is None or current_total is None:
            continue
        if current_total > previous_total:
            observed[label][floor_hour(current_at)] += current_total - previous_total


def hourly_points(
    hours: list[datetime],
    *,
    daily_totals: dict[str, int],
    observed: dict[datetime, int],
    now: datetime,
) -> list[HistoryPoint]:
    """Allocate daily totals across eligible hourly points.

    Returns:
        The resulting collection.

    """
    allocations: dict[datetime, tuple[int, int]] = {}
    dates = sorted({hour.date() for hour in hours})
    for day in dates:
        total = int(daily_totals.get(day.isoformat(), 0))
        if total > 0:
            allocations.update(
                _day_allocations(day, total=total, observed=observed, now=now),
            )

    points: list[HistoryPoint] = []
    for hour in hours:
        tokens, observed_tokens = allocations.get(hour, (0, 0))
        points.append(_history_point(hour, tokens, observed_tokens))
    return points


def _day_allocations(
    day: date,
    *,
    total: int,
    observed: dict[datetime, int],
    now: datetime,
) -> dict[datetime, tuple[int, int]]:
    active_hours = _active_hours(day, now=now)
    observed_items = observed.items()
    same_day_items = (
        item for item in observed_items if item[0].date() == day
    )
    active_items = (
        item for item in same_day_items if item[0] in active_hours
    )
    positive_items = (
        item for item in active_items if item[1] > 0
    )
    observed_for_day = dict(positive_items)
    observed_values = _bounded_observed(observed_for_day, total=total)
    reconstructed = _distribute_integer(
        total - sum(observed_values.values()),
        active_hours,
    )
    allocations: dict[datetime, tuple[int, int]] = {}
    for hour in active_hours:
        sampled = observed_values.get(hour, 0)
        allocations[hour] = (reconstructed.get(hour, 0) + sampled, sampled)
    return allocations


def _active_hours(day: date, *, now: datetime) -> list[datetime]:
    hours: list[datetime] = []
    for hour_number in range(24):
        historical_day = day < now.date()
        elapsed_today = hour_number <= now.hour
        if historical_day or elapsed_today:
            hours.append(
                datetime(day.year, day.month, day.day, hour_number, tzinfo=UTC),
            )
    return hours


def _history_point(
    hour: datetime,
    tokens: int,
    observed_tokens: int,
) -> HistoryPoint:
    return {
        "at": isoformat(hour),
        "tokens": tokens,
        "observed_tokens": observed_tokens,
        "reconstructed_tokens": max(0, tokens - observed_tokens),
        "provenance": provenance(tokens, observed_tokens),
        "smoothed_tokens": 0,
    }


def _bounded_observed(
    values: dict[datetime, int],
    *,
    total: int,
) -> dict[datetime, int]:
    observed_total = sum(values.values())
    if observed_total <= total:
        return values
    if observed_total <= 0:
        return {}
    weights: dict[datetime, float] = {}
    for hour, value in values.items():
        weights[hour] = value / observed_total
    return _distribute_weighted(total, weights)


def _distribute_integer(total: int, keys: list[datetime]) -> dict[datetime, int]:
    if total <= 0 or not keys:
        return dict.fromkeys(keys, 0)
    base, remainder = divmod(total, len(keys))
    distributed: dict[datetime, int] = {}
    for index, key in enumerate(keys):
        distributed[key] = base + int(index < remainder)
    return distributed


def _distribute_weighted(
    total: int,
    weights: dict[datetime, float],
) -> dict[datetime, int]:
    raw: dict[datetime, float] = {}
    result: dict[datetime, int] = {}
    for key, weight in weights.items():
        raw[key] = total * weight
        result[key] = math.floor(raw[key])
    remainder = total - sum(result.values())
    order = sorted(raw, key=lambda key: raw[key] - result[key], reverse=True)
    for key in order[:remainder]:
        result[key] += 1
    return result


def add_smoothed_values(points: list[HistoryPoint]) -> None:
    """Attach a centered, weighted five-point moving average."""
    values = [float(point.get("tokens") or 0) for point in points]
    weights = (1, 2, 3, 2, 1)
    for index, point in enumerate(points):
        weighted = 0.0
        divisor = 0
        for offset, weight in zip(range(-2, 3), weights, strict=False):
            candidate = index + offset
            if 0 <= candidate < len(values):
                weighted += values[candidate] * weight
                divisor += weight
        point["smoothed_tokens"] = round(weighted / divisor) if divisor else 0


def provenance(tokens: int, observed_tokens: int) -> str:
    """Describe whether one point is sampled, reconstructed, or blended.

    Returns:
        The resulting text.

    """
    if observed_tokens <= 0:
        return "reconstructed" if tokens > 0 else "none"
    return "observed" if observed_tokens >= tokens else "blended"
