# Copyright (c) 2026 PitchAI. All rights reserved.
"""Compute bounded retained-sample reliability metrics."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .json_types import (
    bool_value,
    float_value,
    normalized_list_reference,
    normalized_object_reference,
    text_value,
)

if TYPE_CHECKING:
    from .json_types import JsonObject, JsonValue

WINDOW_SECONDS = 86_400.0
PERCENT = 100.0
_MIN_SAMPLE_FIELDS = 2


def samples_for_group(
    domains: list[JsonObject],
    *,
    group_id: str,
    state: JsonObject,
    now_ts: float,
) -> list[list[JsonValue]]:
    """Return valid 24-hour samples for enabled members of one group."""
    history = normalized_object_reference(state.get("history"))
    samples: list[list[JsonValue]] = []
    for domain in domains:
        if text_value(domain.get("group")) != group_id or bool_value(domain.get("disabled")) is True:
            continue
        domain_name = text_value(domain.get("domain"))
        for raw in normalized_list_reference(history.get(domain_name)):
            sample = normalized_list_reference(raw)
            timestamp = float_value(sample[0]) if sample else None
            if (
                len(sample) >= _MIN_SAMPLE_FIELDS
                and timestamp is not None
                and now_ts - WINDOW_SECONDS <= timestamp <= now_ts
            ):
                samples.append(sample)
    samples.sort(key=lambda sample: float_value(sample[0]) or 0.0)
    return samples


def availability(samples: list[list[JsonValue]]) -> tuple[int, int, float | None]:
    """Return total, successful, and availability percent."""
    total = len(samples)
    successful = sum(1 for sample in samples if bool_value(sample[1]) is True)
    percentage = PERCENT * successful / total if total else None
    return total, successful, percentage


def percentile(samples: list[list[JsonValue]], *, index: int) -> float | None:
    """Return the linearly interpolated p95 at one sample field index."""
    values: list[float] = []
    for sample in samples:
        if len(sample) <= index:
            continue
        value = float_value(sample[index])
        if value is not None:
            values.append(value)
    values.sort()
    if not values:
        return None
    position = 0.95 * (len(values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def trend(samples: list[list[JsonValue]], *, now_ts: float) -> list[JsonObject]:
    """Return twelve bounded two-hour availability buckets."""
    bucket_count = 12
    start = now_ts - WINDOW_SECONDS
    bucket_seconds = WINDOW_SECONDS / bucket_count
    totals = [0] * bucket_count
    successes = [0] * bucket_count
    for sample in samples:
        timestamp = float_value(sample[0])
        if timestamp is None:
            continue
        index = min(bucket_count - 1, max(0, int((timestamp - start) // bucket_seconds)))
        totals[index] += 1
        if bool_value(sample[1]) is True:
            successes[index] += 1
    rows: list[JsonObject] = []
    for index, total in enumerate(totals):
        rows.append(
            {
                "start_at_ts": start + index * bucket_seconds,
                "end_at_ts": start + (index + 1) * bucket_seconds,
                "observations": total,
                "availability_pct": PERCENT * successes[index] / total if total else None,
            },
        )
    return rows
