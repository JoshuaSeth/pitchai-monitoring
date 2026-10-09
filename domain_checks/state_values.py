# Copyright (c) 2026 PitchAI. All rights reserved.
"""Decode persisted JSON collections without changing legacy fallback rules."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from .cycle_values import required_float, required_int

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject, JsonValue


def coerce_bool_dict(value: JsonValue) -> dict[str, bool]:
    """Retain only actual boolean values keyed by domain.

    Returns:
        A new boolean map, empty when the persisted value is not an object.
    """
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if isinstance(item, bool)}


def coerce_int_dict(value: JsonValue) -> dict[str, int]:
    """Decode counters, omitting invalid entries rather than inventing zeroes.

    Returns:
        Independently converted domain counters.
    """
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        with suppress(TypeError, ValueError, OverflowError):
            result[key] = required_int(item)
    return result


def coerce_float_dict(value: JsonValue) -> dict[str, float]:
    """Decode timestamps, retaining the monitor's existing numeric policy.

    Returns:
        Independently converted timestamps, including accepted nonfinite values.
    """
    if not isinstance(value, dict):
        return {}
    result: dict[str, float] = {}
    for key, item in value.items():
        with suppress(TypeError, ValueError, OverflowError):
            result[key] = required_float(item)
    return result


def coerce_str_list_dict(value: JsonValue) -> dict[str, list[str]]:
    """Decode retained address lists with their original order and duplicates.

    Returns:
        Stripped nonempty strings for each list-valued field.
    """
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[str]] = {}
    for key, items in value.items():
        if isinstance(items, list):
            cleaned = (str(item or "").strip() for item in items)
            result[key] = [item for item in cleaned if item]
    return result


def coerce_list_of_dicts(value: JsonValue, *, max_items: int = 500) -> list[JsonObject]:
    """Select the earliest retained objects without copying their contents.

    Returns:
        At most the positive effective limit, preserving each object's identity.
    """
    if not isinstance(value, list):
        return []
    result: list[JsonObject] = []
    for item in value:
        if isinstance(item, dict):
            result.append(item)
            if len(result) >= max(1, int(max_items)):
                break
    return result


def coerce_signal_history(
    value: JsonValue, *, max_samples_per_signal: int = 50_000,
) -> dict[str, list[list[JsonValue]]]:
    """Retain bounded nonempty signal rows in their recorded order.

    Returns:
        A map of trimmed signal names to original sample lists.
    """
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[list[JsonValue]]] = {}
    for key, items in value.items():
        name = key.strip()
        if not name or not isinstance(items, list):
            continue
        samples: list[list[JsonValue]] = []
        for sample in items:
            if isinstance(sample, list) and sample:
                samples.append(sample)
                if len(samples) >= max(1, int(max_samples_per_signal)):
                    break
        if samples:
            result[name] = samples
    return result
