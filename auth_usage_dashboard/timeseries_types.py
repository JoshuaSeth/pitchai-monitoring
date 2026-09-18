# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict JSON and SQLite value types for durable usage history."""

from __future__ import annotations

import math

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
type SqlValue = str | int | float | None
type SqlRow = dict[str, SqlValue]


def optional_object(value: JsonValue) -> JsonObject:
    """Return a JSON object or an explicit empty object."""
    if isinstance(value, dict):
        return value
    return {}


def require_object(value: JsonValue, *, description: str) -> JsonObject:
    """Require one decoded JSON object.

    Returns:
        Validated JSON object.

    Raises:
        TypeError: If the decoded value is not an object.
    """
    if isinstance(value, dict):
        return value
    message = f"{description} must contain a JSON object"
    raise TypeError(message)


def text_value(value: JsonValue) -> str | None:
    """Return non-empty trimmed text when present."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def number_value(value: JsonValue) -> float | None:
    """Return a finite number while excluding booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def nonnegative_integer(value: JsonValue) -> int | None:
    """Return a non-negative integral value while excluding booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = int(value)
    return parsed if parsed >= 0 and parsed == value else None


def optional_flag(value: JsonValue) -> int | None:
    """Encode a strict optional boolean for SQLite.

    Returns:
        One or zero for a boolean, otherwise None.
    """
    if isinstance(value, bool):
        return int(value)
    return None
