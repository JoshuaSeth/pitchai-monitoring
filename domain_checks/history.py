# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed rolling history and availability/latency calculations for the cycle."""

from __future__ import annotations

from bisect import bisect_left
from contextlib import suppress
from typing import TYPE_CHECKING, TypedDict, Unpack

from .cycle_values import required_float
from .history_decode import Sample, coerce_history, sample_timestamp

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .event_bus_delivery import JsonValue

__all__ = [
    "Sample", "append_sample", "coerce_history", "compute_availability", "compute_burn_rate",
    "compute_error_rate_percent", "extract_latency_ms", "latency_percentile_ms", "prune_history", "window_samples",
]

_PERCENT = 100.0
_HTTP_INDEX = 2
_BROWSER_INDEX = 3


class SampleInput(TypedDict):
    """Named inputs retained by the existing append_sample callers."""

    domain: str
    ts: float
    ok: bool
    http_elapsed_ms: float | None
    browser_elapsed_ms: float | None
    status_code: int | None


def append_sample(history: dict[str, list[Sample]], **values: Unpack[SampleInput]) -> None:
    """Append a sample, or insert by timestamp after a backwards clock step."""
    domain = values["domain"]
    if not domain:
        return
    http_ms, browser_ms, status = values["http_elapsed_ms"], values["browser_elapsed_ms"], values["status_code"]
    sample: Sample = [
        float(values["ts"]), bool(values["ok"]),
        float(http_ms) if http_ms is not None else None,
        float(browser_ms) if browser_ms is not None else None,
        int(status) if status is not None else None,
    ]
    items = history.get(domain)
    if items is None:
        history[domain] = [sample]
        return
    if not items or sample_timestamp(items[-1]) <= sample_timestamp(sample):
        items.append(sample)
        return
    timestamps = [sample_timestamp(item) for item in items]
    index = bisect_left(timestamps, sample_timestamp(sample))
    items.insert(index, sample)


def prune_history(history: dict[str, list[Sample]], *, before_ts: float) -> None:
    """Remove only samples older than the cutoff, retaining equality."""
    cutoff = float(before_ts)
    for domain in list(history):
        items = history.get(domain) or []
        if not items:
            del history[domain]
            continue
        timestamps = [sample_timestamp(item) for item in items]
        index = bisect_left(timestamps, cutoff)
        if index <= 0:
            continue
        if index >= len(items):
            del history[domain]
            continue
        history[domain] = items[index:]


def window_samples(items: list[Sample], *, since_ts: float) -> list[Sample]:
    """Select retained samples at or after the requested timestamp.

    Returns:
        The original sample rows in a new list, including cutoff equality.
    """
    if not items:
        return []
    cutoff = float(since_ts)
    timestamps = [sample_timestamp(item) for item in items]
    index = bisect_left(timestamps, cutoff)
    return items[index:]


def compute_availability(items: list[Sample]) -> tuple[int, int, float | None]:
    """Count retained effective-health observations.

    Returns:
        Total count, healthy count and percentage, or None for an empty window.
    """
    total = len(items)
    if total <= 0:
        return 0, 0, None
    healthy = sum(1 for sample in items if bool(sample[1]))
    percentage = (healthy / float(total)) * _PERCENT
    return total, healthy, percentage


def compute_error_rate_percent(items: list[Sample]) -> float | None:
    """Calculate errors from retained effective-health observations.

    Returns:
        The error percentage, or None when no observations are available.
    """
    total = len(items)
    if total <= 0:
        return None
    healthy = sum(1 for sample in items if bool(sample[1]))
    errors = total - healthy
    return (errors / float(total)) * _PERCENT


def _percentile(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    percentile = float(p)
    if percentile <= 0:
        return float(sorted_values[0])
    if percentile >= _PERCENT:
        return float(sorted_values[-1])
    index = round((percentile / _PERCENT) * (len(sorted_values) - 1))
    index = max(0, min(index, len(sorted_values) - 1))
    return float(sorted_values[index])


def extract_latency_ms(items: Iterable[JsonValue], *, field: str) -> list[float]:
    """Read available HTTP or browser latency fields with legacy fallbacks.

    Returns:
        Converted latencies in input order; malformed or absent values omitted.
    """
    index = _HTTP_INDEX if field == "http_elapsed_ms" else _BROWSER_INDEX
    result: list[float] = []
    for sample in items:
        if not isinstance(sample, list) or len(sample) <= index:
            continue
        value = sample[index]
        if value is None:
            continue
        with suppress(TypeError, ValueError, OverflowError):
            result.append(required_float(value))
    return result


def latency_percentile_ms(items: list[Sample], *, field: str, percentile: float) -> float | None:
    """Apply the existing rounded-rank calculation to available latencies.

    Returns:
        The selected latency, or None when no latency values are available.
    """
    values = extract_latency_ms(items, field=field)
    values.sort()
    return _percentile(values, percentile)


def compute_burn_rate(items: list[Sample], *, slo_target_percent: float) -> float | None:
    """Divide the observed error rate by the configured SLO error budget.

    Returns:
        The original burn-rate calculation, or None for absent/invalid inputs.
    """
    total, healthy, _percentage = compute_availability(items)
    if total <= 0:
        return None
    target = float(slo_target_percent)
    if not 0.0 < target < _PERCENT:
        return None
    budget = 1.0 - (target / _PERCENT)
    if budget <= 0.0:
        return None
    error_rate = (total - healthy) / float(total)
    return error_rate / budget
