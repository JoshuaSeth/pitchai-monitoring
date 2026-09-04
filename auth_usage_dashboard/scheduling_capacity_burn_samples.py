# Copyright (c) 2026 PitchAI. All rights reserved.
"""Aggregate continuous broker samples into reset-aware burn measurements."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from itertools import pairwise
from typing import TYPE_CHECKING

from .history import isoformat, parse_datetime
from .scheduling_capacity_burn_deltas import account_deltas, eligible_labels
from .timeseries_types import optional_object, text_value

if TYPE_CHECKING:
    from .timeseries_types import JsonObject

_MAX_SAMPLE_GAP_SECONDS = 20 * 60
type BurnPeriod = tuple[datetime, datetime]


@dataclass(frozen=True)
class _IntervalBurn:
    """Measured burn and coverage for one clipped sample interval."""

    capacity_points: float
    provider_tokens: float
    covered_seconds: float
    capacity_labels: frozenset[str]
    token_labels: frozenset[str]
    sample_times: frozenset[str]


@dataclass
class BurnWindowTotals:
    """Mutable accumulator for one requested measurement window."""

    capacity_points: float = 0.0
    provider_tokens: float = 0.0
    covered_seconds: float = 0.0
    capacity_labels: set[str] = field(default_factory=set)
    token_labels: set[str] = field(default_factory=set)
    sample_times: set[str] = field(default_factory=set)

    def add(self, interval: _IntervalBurn) -> None:
        """Add one valid interval without double-counting wall-clock coverage."""
        self.capacity_points += interval.capacity_points
        self.provider_tokens += interval.provider_tokens
        self.covered_seconds += interval.covered_seconds
        self.capacity_labels.update(interval.capacity_labels)
        self.token_labels.update(interval.token_labels)
        self.sample_times.update(interval.sample_times)


def measure_burn_samples(
    accounts: list[JsonObject],
    samples: list[JsonObject],
    *,
    starts_at: datetime,
    ends_at: datetime,
    window_key: str,
) -> BurnWindowTotals:
    """Measure all valid continuous intervals in the requested time range."""
    totals = BurnWindowTotals()
    labels = eligible_labels(accounts)
    for previous, current in pairwise(_timed_samples(samples)):
        interval = _measure_interval(
            previous,
            current,
            labels=labels,
            period=(starts_at, ends_at),
            window_key=window_key,
        )
        if interval is not None:
            totals.add(interval)
    return totals


def _timed_samples(samples: list[JsonObject]) -> list[tuple[datetime, JsonObject]]:
    timed: list[tuple[datetime, JsonObject]] = []
    for sample in samples:
        at = parse_datetime(text_value(sample.get("at")))
        if at is not None:
            timed.append((at, sample))
    return sorted(timed, key=lambda item: item[0])


def _measure_interval(
    previous: tuple[datetime, JsonObject],
    current: tuple[datetime, JsonObject],
    *,
    labels: set[str],
    period: BurnPeriod,
    window_key: str,
) -> _IntervalBurn | None:
    previous_at, previous_sample = previous
    current_at, current_sample = current
    overlap = _interval_overlap(previous_at, current_at, period=period)
    if overlap is None:
        return None
    deltas = account_deltas(
        optional_object(previous_sample.get("accounts")),
        optional_object(current_sample.get("accounts")),
        labels=labels,
        sample_times=(previous_at, current_at),
        window_key=window_key,
    )
    return _burn_from_deltas(
        deltas,
        overlap=overlap,
        sample_times=(previous_at, current_at),
    )


def _burn_from_deltas(
    deltas: dict[str, tuple[float | None, int | None]],
    *,
    overlap: tuple[float, float],
    sample_times: tuple[datetime, datetime],
) -> _IntervalBurn | None:
    overlap_seconds, fraction = overlap
    capacity_labels = _covered_labels(deltas, index=0)
    token_labels = _covered_labels(deltas, index=1)
    if not capacity_labels and not token_labels:
        return None
    capacity_points, provider_tokens = _scaled_totals(deltas, fraction=fraction)
    previous_at, current_at = sample_times
    return _IntervalBurn(
        capacity_points=capacity_points,
        provider_tokens=provider_tokens,
        covered_seconds=overlap_seconds if capacity_labels else 0.0,
        capacity_labels=capacity_labels,
        token_labels=token_labels,
        sample_times=frozenset((isoformat(previous_at), isoformat(current_at))),
    )


def _interval_overlap(
    previous_at: datetime,
    current_at: datetime,
    *,
    period: BurnPeriod,
) -> tuple[float, float] | None:
    starts_at, ends_at = period
    interval_seconds = (current_at - previous_at).total_seconds()
    overlap_seconds = (
        min(current_at, ends_at) - max(previous_at, starts_at)
    ).total_seconds()
    if interval_seconds <= 0 or interval_seconds > _MAX_SAMPLE_GAP_SECONDS:
        return None
    if overlap_seconds <= 0:
        return None
    return overlap_seconds, overlap_seconds / interval_seconds


def _covered_labels(
    deltas: dict[str, tuple[float | None, int | None]],
    *,
    index: int,
) -> frozenset[str]:
    covered: set[str] = set()
    for label, delta in deltas.items():
        if delta[index] is not None:
            covered.add(label)
    return frozenset(covered)


def _scaled_totals(
    deltas: dict[str, tuple[float | None, int | None]],
    *,
    fraction: float,
) -> tuple[float, float]:
    capacity_points = 0.0
    provider_tokens = 0
    for capacity_delta, token_delta in deltas.values():
        capacity_points += capacity_delta or 0.0
        provider_tokens += token_delta or 0
    return capacity_points * fraction, provider_tokens * fraction
