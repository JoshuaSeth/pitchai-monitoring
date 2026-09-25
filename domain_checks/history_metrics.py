# Copyright (c) 2026 PitchAI. All rights reserved.
"""Availability, latency, and burn-rate calculations for monitor history."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable

    from domain_checks.history import Sample

_OK_INDEX = 1
_HTTP_LATENCY_INDEX = 2
_BROWSER_LATENCY_INDEX = 3
_PERCENT = 100.0


def compute_availability(items: list[Sample]) -> tuple[int, int, float | None]:
    """Compute sample availability.

    Returns:
        The total, successful count, and success percentage when available.
    """
    total = len(items)
    if total <= 0:
        return 0, 0, None
    ok_count = sum(1 for sample in items if sample[_OK_INDEX])
    ok_pct = (ok_count / float(total)) * _PERCENT
    return total, ok_count, ok_pct


def compute_error_rate_percent(items: list[Sample]) -> float | None:
    """Compute the failed-sample percentage.

    Returns:
        The error percentage, or ``None`` when no samples exist.
    """
    total = len(items)
    if total <= 0:
        return None
    ok_count = sum(1 for sample in items if sample[_OK_INDEX])
    err_count = total - ok_count
    return (err_count / float(total)) * _PERCENT


def _percentile(sorted_values: list[float], percentile: float) -> float | None:
    if not sorted_values:
        return None
    selected_percentile = float(percentile)
    if selected_percentile <= 0:
        return float(sorted_values[0])
    if selected_percentile >= _PERCENT:
        return float(sorted_values[-1])
    index = round(
        (selected_percentile / _PERCENT) * (len(sorted_values) - 1),
    )
    bounded_index = max(0, min(index, len(sorted_values) - 1))
    return float(sorted_values[bounded_index])


def extract_latency_ms(
    items: Iterable[Sample],
    *,
    field: Literal["http_elapsed_ms", "browser_elapsed_ms"],
) -> list[float]:
    """Extract non-null latency values for one sample field.

    Returns:
        The extracted latency values in sample order.
    """
    index = _HTTP_LATENCY_INDEX if field == "http_elapsed_ms" else _BROWSER_LATENCY_INDEX
    values: list[float] = []
    for sample in items:
        value = sample[index]
        if value is not None:
            values.append(float(value))
    return values


def latency_percentile_ms(
    items: list[Sample],
    *,
    field: Literal["http_elapsed_ms", "browser_elapsed_ms"],
    percentile: float,
) -> float | None:
    """Compute a nearest-rank latency percentile.

    Returns:
        The selected latency percentile, or ``None`` when no values exist.
    """
    values = extract_latency_ms(items, field=field)
    values.sort()
    return _percentile(values, percentile)


def compute_burn_rate(
    items: list[Sample],
    *,
    slo_target_percent: float,
) -> float | None:
    """Compute burn rate as error rate divided by the error budget.

    Returns:
        The burn rate, or ``None`` when it cannot be computed.
    """
    total, ok_count, _ok_pct = compute_availability(items)
    target = float(slo_target_percent)
    if total <= 0 or not 0.0 < target < _PERCENT:
        return None
    budget = 1.0 - (target / _PERCENT)
    if budget <= 0.0:
        return None
    err_rate = (total - ok_count) / float(total)
    return err_rate / budget
