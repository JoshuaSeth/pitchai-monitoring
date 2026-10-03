# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed decoding of the monitor's retained five-field history samples."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from .cycle_values import coerce_optional_float, required_float, required_int

if TYPE_CHECKING:
    from .event_bus_delivery import JsonValue

# Persisted encoding: [timestamp, effective_ok, http_ms, browser_ms, status].
# JSON values remain accepted at the boundary so malformed older samples can
# use the original omission/fallback rules without an untyped escape.
type Sample = list[JsonValue]

_MIN_FIELDS = 2
_HTTP_INDEX = 2
_BROWSER_INDEX = 3
_STATUS_INDEX = 4


def sample_timestamp(sample: Sample) -> float:
    """Read a sample's timestamp with the original falsey-value fallback.

    Returns:
        The numeric timestamp used for sorting and interval selection.
    """
    if not sample[0]:
        return 0.0
    return required_float(sample[0])


def coerce_history(raw: JsonValue) -> dict[str, list[Sample]]:
    """Normalize retained history while omitting invalid domains and samples.

    Returns:
        Sorted five-field samples for each nonempty domain history.
    """
    if not isinstance(raw, dict):
        return {}
    result: dict[str, list[Sample]] = {}
    for domain, items in raw.items():
        if not domain or not isinstance(items, list):
            continue
        samples: list[Sample] = []
        for item in items:
            sample = _decode_sample(item)
            if sample is not None:
                samples.append(sample)
        samples.sort(key=sample_timestamp)
        if samples:
            result[domain] = samples
    return result


def _decode_sample(item: JsonValue) -> Sample | None:
    if not isinstance(item, list) or len(item) < _MIN_FIELDS:
        return None
    timestamp: float | None = None
    with suppress(TypeError, ValueError, OverflowError):
        timestamp = required_float(item[0])
    if timestamp is None:
        return None
    http_ms = coerce_optional_float(item[_HTTP_INDEX]) if len(item) > _HTTP_INDEX else None
    browser_ms = coerce_optional_float(item[_BROWSER_INDEX]) if len(item) > _BROWSER_INDEX else None
    status: int | None = None
    if len(item) > _STATUS_INDEX:
        with suppress(TypeError, ValueError, OverflowError):
            status = required_int(item[_STATUS_INDEX])
    return [timestamp, bool(item[1]), http_ms, browser_ms, status]
