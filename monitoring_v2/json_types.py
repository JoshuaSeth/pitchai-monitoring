# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict JSON normalization shared by monitoring collectors and dashboard IO."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import cast

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
type JsonInput = JsonScalar | Mapping[str, JsonInput] | Sequence[JsonInput]


def normalize_json(value: JsonInput) -> JsonValue:
    """Normalize a runtime value into an explicit JSON-compatible value.

    Returns:
        A recursively normalized JSON-compatible value.

    Raises:
        TypeError: If a boundary value cannot be encoded without inventing a
            representation.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        raw_mapping = cast("Mapping[object, JsonInput]", value)
        normalized: JsonObject = {}
        for key, item in raw_mapping.items():
            if not isinstance(key, str):
                message = f"monitoring JSON object key must be text, got {type(key).__name__}"
                raise TypeError(message)
            normalized[key] = normalize_json(item)
        return normalized
    sequence = cast("Sequence[JsonInput]", value)
    return [normalize_json(item) for item in sequence]


def json_object(value: JsonInput) -> JsonObject:
    """Normalize and require a top-level JSON object.

    Returns:
        A normalized JSON object.

    Raises:
        TypeError: If the value is not a JSON object.
    """
    normalized = normalize_json(value)
    if isinstance(normalized, dict):
        return normalized
    message = f"monitoring value must be an object, got {type(normalized).__name__}"
    raise TypeError(message)


def optional_object(value: JsonValue | object) -> JsonObject:
    """Return an object or an explicit missing-state object at an IO edge."""
    if not isinstance(value, dict):
        return {}
    raw_mapping = cast("dict[object, object]", value)
    normalized: JsonObject = {}
    for key, item in raw_mapping.items():
        if isinstance(key, str):
            normalized[key] = normalize_json(cast("JsonInput", item))
    return normalized


def object_list(value: JsonValue | object) -> list[JsonObject]:
    """Return only object members from a JSON array."""
    if not isinstance(value, list):
        return []
    raw_items = cast("list[object]", value)
    return [optional_object(cast("JsonInput", item)) for item in raw_items if isinstance(item, dict)]


def value_list(value: JsonValue | object) -> list[JsonValue]:
    """Return a copied JSON array or an explicit empty state."""
    if not isinstance(value, list):
        return []
    raw_items = cast("list[object]", value)
    return [normalize_json(cast("JsonInput", item)) for item in raw_items]


def normalized_object_reference(value: JsonValue) -> JsonObject:
    """Return an already-normalized object without recursively copying it.

    This accessor is only for values reached through a ``JsonObject`` that has
    already crossed a normalization boundary. Callers must treat the returned
    object as read-only.

    Returns:
        The existing object, or an explicit missing-state object.
    """
    if isinstance(value, dict):
        return value
    return {}


def normalized_list_reference(value: JsonValue) -> list[JsonValue]:
    """Return an already-normalized list without recursively copying it.

    This accessor is only for values reached through a ``JsonObject`` that has
    already crossed a normalization boundary. Callers must treat the returned
    list as read-only.

    Returns:
        The existing list, or an explicit missing-state list.
    """
    if isinstance(value, list):
        return value
    return []


def text_value(value: JsonValue | object, *, default: str = "") -> str:
    """Return text without coercing structured data into misleading copy."""
    if isinstance(value, str):
        return value
    return default


def float_value(value: JsonValue | object) -> float | None:
    """Return a finite numeric value while excluding booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def int_value(value: JsonValue | object) -> int | None:
    """Return an integer value when the source is integral and not boolean."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def bool_value(value: JsonValue | object) -> bool | None:
    """Return a strict boolean without truthiness coercion."""
    if isinstance(value, bool):
        return value
    return None
