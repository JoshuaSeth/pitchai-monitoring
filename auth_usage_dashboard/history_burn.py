# Copyright (c) 2026 PitchAI. All rights reserved.
"""Derive capacity burn from native samples or current provider windows."""

from __future__ import annotations

import itertools
import math
from datetime import timedelta
from typing import TYPE_CHECKING, NamedTuple

from .history_store import sample_at
from .history_windows import current_window_rates, sample_window
from .value_parsing import UTC

if TYPE_CHECKING:
    from datetime import datetime

    from .models import (
        CapacityAccount,
        CapacityBurnRate,
        SampleWindow,
        UsageSample,
        UsageSampleAccount,
    )

_HIGH_CONFIDENCE_ACCOUNT_COUNT = 2
_HIGH_CONFIDENCE_SAMPLE_COUNT = 9
_MIN_FALLBACK_RATE_COUNT = 2
_MIN_NATIVE_INTERVAL_COUNT = 3
_MIN_VARIATION_SAMPLE_COUNT = 3


class NativeBurn(NamedTuple):
    """Aggregate comparable native sample intervals."""

    rates: list[float]
    sampled_points: float
    sampled_hours: float
    covered_labels: set[str]
    recent_count: int


class BurnSelection(NamedTuple):
    """Bundle the selected burn estimate and its provenance."""

    fallback_rates: list[float]
    rate: float
    source: str
    confidence: str


def capacity_burn_rate(
    accounts: list[CapacityAccount],
    *,
    samples: list[UsageSample],
    now: datetime,
    window_key: str = "five_hour",
    lookback_hours: int = 2,
) -> CapacityBurnRate:
    """Estimate aggregate capacity points consumed per hour.

    Returns:
        The resulting value.

    """
    now = now.astimezone(UTC)
    cutoff = now - timedelta(hours=lookback_hours)
    native = _native_burn(samples, cutoff=cutoff, now=now, window_key=window_key)
    native_rate = native.sampled_points / native.sampled_hours if native.sampled_hours > 0 else None
    fallback_rates = current_window_rates(accounts, now=now, window_key=window_key)
    if native_rate is not None and native.recent_count >= _MIN_NATIVE_INTERVAL_COUNT:
        rate = native_rate
        source = "native_broker_samples"
        confidence = _native_confidence(native)
    else:
        rate = sum(fallback_rates)
        source = "current_window_average"
        confidence = "medium" if len(fallback_rates) >= _MIN_FALLBACK_RATE_COUNT else "low"
    selection = BurnSelection(fallback_rates, rate, source, confidence)
    return _burn_payload(
        native,
        selection,
        window_key=window_key,
        lookback_hours=lookback_hours,
    )


def _native_burn(
    samples: list[UsageSample],
    *,
    cutoff: datetime,
    now: datetime,
    window_key: str,
) -> NativeBurn:
    recent: list[UsageSample] = [
        sample for sample in samples if (sample_at(sample) or now) >= cutoff - timedelta(minutes=15)
    ]
    intervals: list[tuple[float, float, set[str]]] = []
    for previous, current in itertools.pairwise(recent):
        interval = _sample_interval(
            previous,
            current,
            cutoff=cutoff,
            window_key=window_key,
        )
        if interval is not None:
            intervals.append(interval)
    return _summarize_intervals(intervals, recent_count=len(recent))


def _summarize_intervals(
    intervals: list[tuple[float, float, set[str]]],
    *,
    recent_count: int,
) -> NativeBurn:
    rates: list[float] = []
    sampled_points = 0.0
    sampled_hours = 0.0
    covered_labels: set[str] = set()
    for points, hours, labels in intervals:
        rates.append(points / hours)
        sampled_points += points
        sampled_hours += hours
        covered_labels.update(labels)
    return NativeBurn(
        rates,
        sampled_points,
        sampled_hours,
        covered_labels,
        recent_count,
    )


def _sample_interval(
    previous: UsageSample,
    current: UsageSample,
    *,
    cutoff: datetime,
    window_key: str,
) -> tuple[float, float, set[str]] | None:
    previous_at = sample_at(previous)
    current_at = sample_at(current)
    if previous_at is None or current_at is None:
        return None
    if current_at <= previous_at or current_at < cutoff:
        return None
    hours = (current_at - max(previous_at, cutoff)).total_seconds() / 3600.0
    if hours <= 0:
        return None
    points, labels = _interval_points(
        previous.get("accounts", {}),
        current.get("accounts", {}),
        previous_at=previous_at,
        current_at=current_at,
        window_key=window_key,
    )
    return (points, hours, labels) if labels else None


def _interval_points(
    previous_accounts: dict[str, UsageSampleAccount],
    current_accounts: dict[str, UsageSampleAccount],
    *,
    previous_at: datetime,
    current_at: datetime,
    window_key: str,
) -> tuple[float, set[str]]:
    points = 0.0
    covered_labels: set[str] = set()
    for label, current_account in current_accounts.items():
        previous_account = previous_accounts.get(label)
        if previous_account is None:
            continue
        previous_window = sample_window(
            previous_account,
            at=previous_at,
            key=window_key,
        )
        current_window = sample_window(
            current_account,
            at=current_at,
            key=window_key,
        )
        if not _comparable_windows(previous_window, current_window):
            continue
        if current_window is None or previous_window is None:
            continue
        points += current_window["used_percent"] - previous_window["used_percent"]
        covered_labels.add(label)
    return points, covered_labels


def _comparable_windows(
    previous: SampleWindow | None,
    current: SampleWindow | None,
) -> bool:
    if previous is None or current is None:
        return False
    return previous["reset_at"] == current["reset_at"] and current["used_percent"] >= previous["used_percent"]


def _native_confidence(native: NativeBurn) -> str:
    if (
        native.recent_count >= _HIGH_CONFIDENCE_SAMPLE_COUNT
        and len(native.covered_labels) >= _HIGH_CONFIDENCE_ACCOUNT_COUNT
    ):
        return "high"
    return "medium"


def _burn_payload(
    native: NativeBurn,
    selection: BurnSelection,
    *,
    window_key: str,
    lookback_hours: int,
) -> CapacityBurnRate:
    variation = _coefficient_of_variation(native.rates)
    if variation is None:
        variation = 0.4 if selection.confidence == "medium" else 0.65
    uses_native = selection.source == "native_broker_samples"
    return {
        "capacity_points_per_hour": round(max(0.0, selection.rate), 2),
        "source": selection.source,
        "window_key": window_key,
        "lookback_hours": lookback_hours if uses_native else None,
        "fallback_window": (None if uses_native else f"current {window_key.replace('_', '-')} windows"),
        "confidence": selection.confidence,
        "sample_count": native.recent_count,
        "covered_accounts": (len(native.covered_labels) if uses_native else len(selection.fallback_rates)),
        "coefficient_of_variation": round(min(1.5, max(0.15, variation)), 3),
        "native_interval_rates": [round(value, 3) for value in native.rates[-24:]],
    }


def _coefficient_of_variation(values: list[float]) -> float | None:
    positive = [value for value in values if value >= 0]
    if len(positive) < _MIN_VARIATION_SAMPLE_COUNT:
        return None
    mean = sum(positive) / len(positive)
    if mean <= 0:
        return None
    squared_deviations = [(value - mean) ** 2 for value in positive]
    variance = sum(squared_deviations) / (len(positive) - 1)
    return math.sqrt(variance) / mean
