# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict value parsing shared by monitor configuration and persisted state."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain_checks.types import JsonObject, JsonValue


def json_float(value: JsonValue) -> float:
    """Convert a JSON scalar to a float or fail loudly.

    Returns:
        The converted floating-point value.

    Raises:
        TypeError: The value is not a JSON scalar.
    """
    if isinstance(value, bool | int | float | str):
        return float(value)
    message = f"Expected a scalar numeric value, got {type(value).__name__}"
    raise TypeError(message)


def json_int(value: JsonValue) -> int:
    """Convert a JSON scalar to an integer or fail loudly.

    Returns:
        The converted integer value.

    Raises:
        TypeError: The value is not a JSON scalar.
    """
    if isinstance(value, bool | int | float | str):
        return int(value)
    message = f"Expected a scalar integer value, got {type(value).__name__}"
    raise TypeError(message)


def json_array(value: JsonValue) -> list[JsonValue]:
    """Return a JSON array or an empty array for an absent optional value.

    Returns:
        The array value, or an empty array when absent or invalid.
    """
    return value if isinstance(value, list) else []


def json_object(value: JsonValue) -> JsonObject:
    """Return a JSON object or an empty object for an absent optional value.

    Returns:
        The object value, or an empty object when absent or invalid.
    """
    return value if isinstance(value, dict) else {}


def object_config(config: JsonObject, key: str) -> JsonObject:
    """Read an optional mapping-valued configuration section.

    Returns:
        The configured object, or an empty object when absent.

    Raises:
        TypeError: The configured value is not an object.
    """
    raw = config.get(key)
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    message = f"Config key {key!r} must be a mapping"
    raise TypeError(message)


def string_list(value: JsonValue, *, description: str) -> list[str]:
    """Read a strict optional list of non-empty strings.

    Returns:
        The normalized string values.

    Raises:
        TypeError: The value or one of its entries has the wrong type.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        message = f"{description} must be a list of strings"
        raise TypeError(message)
    values: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            message = f"{description}[{index}] must be a string"
            raise TypeError(message)
        cleaned = item.strip()
        if cleaned:
            values.append(cleaned)
    return values


def bool_value(value: JsonValue, *, default: bool) -> bool:
    """Read a persisted boolean with an explicit schema default.

    Returns:
        The boolean value or the supplied default.
    """
    return value if isinstance(value, bool) else default


def int_value(value: JsonValue, *, default: int = 0) -> int:
    """Read a persisted integer with an explicit schema default.

    Returns:
        The converted integer or the supplied default.
    """
    try:
        return json_int(value)
    except (TypeError, ValueError):
        return default


def float_value(value: JsonValue, *, default: float = 0.0) -> float:
    """Read a persisted float with an explicit schema default.

    Returns:
        The converted float or the supplied default.
    """
    try:
        return json_float(value)
    except (TypeError, ValueError):
        return default


def optional_float(value: JsonValue) -> float | None:
    """Read an optional float from a configuration boundary.

    Returns:
        The converted float, or ``None`` when absent or invalid.
    """
    if value is None:
        return None
    try:
        return json_float(value)
    except (TypeError, ValueError):
        return None
