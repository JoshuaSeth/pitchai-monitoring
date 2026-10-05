# Copyright (c) 2026 PitchAI. All rights reserved.
"""Capacity burn-rate estimation from native samples or current windows."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING

from .history_values import (
    eligible_accounts,
    isoformat,
    parse_datetime,
    sample_accounts,
    sample_integer,
    sample_number,
)
from .timeseries_types import optional_object

if TYPE_CHECKING:
    from datetime import datetime

    from .timeseries_types import JsonObject

type SampleWindow = tuple[float, str]
type SampleTimes = tuple[datetime, datetime]
type RateChoice = tuple[float, str, str]

_NATIVE_SOURCE = "native_broker_samples"
_RECENT_SAMPLE_SLACK = timedelta(minutes=15)
_LEGACY_FIVE_HOUR_HORIZON = timedelta(hours=6)
_NATIVE_MINIMUM_SAMPLES = 3
_HIGH_CONFIDENCE_SAMPLES = 9
_MULTIPLE_ACCOUNTS = 2
_MINIMUM_VARIATION_RATES = 3
_MEDIUM_DEFAULT_VARIATION = 0.4
_LOW_DEFAULT_VARIATION = 0.65
_VARIATION_FLOOR = 0.15
_VARIATION_CEILING = 1.5
_REPORTED_RATE_COUNT = 24
_DEFAULT_WINDOW_SECONDS = 18_000


@dataclass
class _NativeBurn:
    rates: list[float] = field(default_factory=list[float])
    points: float = 0.0
    hours: float = 0.0
    labels: set[str] = field(default_factory=set[str])


def capacity_burn_rate(
    accounts: list[JsonObject],
    *,
    samples: list[JsonObject],
    now: datetime,
    window_key: str = "five_hour",
    lookback_hours: int = 2,
) -> JsonObject:
    """Estimate aggregate capacity points consumed per hour.

    Native broker samples are preferred; current provider windows provide a
    fallback average when too few native intervals exist.

    Returns:
        The burn estimate with its source, confidence, and dispersion.
    """
    current = now.astimezone(UTC)
    cutoff = current - timedelta(hours=lookback_hours)
    recent = [
        sample for sample in samples if (parse_datetime(sample.get("at")) or current) >= cutoff - _RECENT_SAMPLE_SLACK
    ]
    native = _native_burn(recent, cutoff=cutoff, window_key=window_key)
    fallback_rates = _current_window_rates(accounts, now=current, window_key=window_key)
    rate, source, confidence = _choose_rate(native, sample_count=len(recent), fallback_rates=fallback_rates)
    variation = _coefficient_of_variation(native.rates)
    if variation is None:
        variation = _MEDIUM_DEFAULT_VARIATION if confidence == "medium" else _LOW_DEFAULT_VARIATION
    native_source = source == _NATIVE_SOURCE
    return {
        "capacity_points_per_hour": round(max(0.0, rate), 2),
        "source": source,
        "window_key": window_key,
        "lookback_hours": lookback_hours if native_source else None,
        "fallback_window": None if native_source else f"current {window_key.replace('_', '-')} windows",
        "confidence": confidence,
        "sample_count": len(recent),
        "covered_accounts": len(native.labels) if native_source else len(fallback_rates),
        "coefficient_of_variation": round(min(_VARIATION_CEILING, max(_VARIATION_FLOOR, variation)), 3),
        "native_interval_rates": [round(value, 3) for value in native.rates[-_REPORTED_RATE_COUNT:]],
    }


def _choose_rate(native: _NativeBurn, *, sample_count: int, fallback_rates: list[float]) -> RateChoice:
    if native.hours > 0 and sample_count >= _NATIVE_MINIMUM_SAMPLES:
        many_samples = sample_count >= _HIGH_CONFIDENCE_SAMPLES
        confidence = "high" if many_samples and len(native.labels) >= _MULTIPLE_ACCOUNTS else "medium"
        return native.points / native.hours, _NATIVE_SOURCE, confidence
    confidence = "medium" if len(fallback_rates) >= _MULTIPLE_ACCOUNTS else "low"
    return sum(fallback_rates), "current_window_average", confidence


def _native_burn(recent: list[JsonObject], *, cutoff: datetime, window_key: str) -> _NativeBurn:
    native = _NativeBurn()
    for previous, current in pairwise(recent):
        previous_at = parse_datetime(previous.get("at"))
        current_at = parse_datetime(current.get("at"))
        if previous_at is None or current_at is None or current_at <= previous_at or current_at < cutoff:
            continue
        hours = (current_at - max(previous_at, cutoff)).total_seconds() / 3600.0
        if hours <= 0:
            continue
        interval = _interval_points(previous, current, times=(previous_at, current_at), window_key=window_key)
        if interval is None:
            continue
        points, labels = interval
        native.labels.update(labels)
        native.rates.append(points / hours)
        native.points += points
        native.hours += hours
    return native


def _interval_points(
    previous: JsonObject,
    current: JsonObject,
    *,
    times: SampleTimes,
    window_key: str,
) -> tuple[float, list[str]] | None:
    current_accounts = sample_accounts(current)
    if not current_accounts:
        return None
    previous_accounts = sample_accounts(previous)
    previous_at, current_at = times
    points = 0.0
    labels: list[str] = []
    for label, current_account in current_accounts.items():
        previous_account = previous_accounts.get(label)
        if not isinstance(previous_account, dict) or not isinstance(current_account, dict):
            continue
        earlier = _sample_window(previous_account, at=previous_at, key=window_key)
        later = _sample_window(current_account, at=current_at, key=window_key)
        if earlier is None or later is None or earlier[1] != later[1] or later[0] < earlier[0]:
            continue
        points += later[0] - earlier[0]
        labels.append(label)
    return (points, labels) if labels else None


def _sample_window(account: JsonObject, *, at: datetime, key: str) -> SampleWindow | None:
    prefix = "five" if key == "five_hour" else "weekly"
    used = sample_number(account.get(f"{prefix}_used_percent"))
    reset_at = parse_datetime(account.get(f"{prefix}_reset_at"))
    if used is not None and reset_at is not None:
        return used, isoformat(reset_at)

    # Samples written before schema v4 called every provider primary window
    # five-hour. A reset more than six hours away cannot be a five-hour window,
    # so it is safe to recover those historical weekly deltas.
    if key == "weekly":
        legacy_used = sample_number(account.get("five_used_percent"))
        legacy_reset = parse_datetime(account.get("five_reset_at"))
        if legacy_used is not None and legacy_reset is not None and legacy_reset - at > _LEGACY_FIVE_HOUR_HORIZON:
            return legacy_used, isoformat(legacy_reset)
    return None


def _current_window_rates(accounts: list[JsonObject], *, now: datetime, window_key: str) -> list[float]:
    rates: list[float] = []
    for account in eligible_accounts(accounts):
        window = optional_object(account.get(window_key))
        if window.get("reported") is not True:
            continue
        used = sample_number(window.get("used_percent"))
        reset_at = parse_datetime(window.get("reset_at"))
        window_seconds = sample_integer(window.get("window_seconds")) or _DEFAULT_WINDOW_SECONDS
        if used is None or reset_at is None:
            continue
        started_at = reset_at - timedelta(seconds=window_seconds)
        elapsed_hours = (now - started_at).total_seconds() / 3600.0
        if 1 / 12 <= elapsed_hours <= window_seconds / 3600.0 + 0.25:
            rates.append(max(0.0, used / elapsed_hours))
    return rates


def _coefficient_of_variation(values: list[float]) -> float | None:
    positive = [value for value in values if value >= 0]
    if len(positive) < _MINIMUM_VARIATION_RATES:
        return None
    mean = sum(positive) / len(positive)
    if mean <= 0:
        return None
    variance = sum((value - mean) ** 2 for value in positive) / (len(positive) - 1)
    return math.sqrt(variance) / mean
