# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed retained-value boundaries for dashboard calculations."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterable

    from domain_checks.config_values import ConfigValue
    from domain_checks.event_bus_delivery import JsonValue

type Record = dict[str, ConfigValue]


def object_or_empty(value: ConfigValue | JsonValue) -> Record:
    """Keep the display's explicit mapping-only fallback.

    Returns:
        The same mapping, or an empty object for a non-mapping value.
    """
    if isinstance(value, dict):
        return cast("Record", value)
    return {}


def required_object(value: ConfigValue | JsonValue, *, operation: str = "get") -> Record:
    """Read an unguarded retained mapping without converting corruption to health.

    Returns:
        The existing mapping without copying it.

    Raises:
        AttributeError: A value lacks the mapping access required by the caller.
    """
    if isinstance(value, dict):
        return cast("Record", value)
    message = f"'{type(value).__name__}' object has no attribute '{operation}'"
    raise AttributeError(message)


def array_or_empty(value: ConfigValue | JsonValue) -> list[ConfigValue]:
    """Keep the display's explicit list-only fallback.

    Returns:
        The same list, or an empty list when the value is not a list.
    """
    if isinstance(value, list):
        return cast("list[ConfigValue]", value)
    return []


def integer(value: ConfigValue | JsonValue) -> int:
    """Preserve scalar int conversion and its malformed persisted-value error.

    Returns:
        The integer-converted scalar.

    Raises:
        TypeError: The JSON/YAML input is not an integer-compatible scalar.
    """
    if isinstance(value, (str, bytes, int, float)):
        return int(value)
    message = f"int() argument must be a string, a bytes-like object or a real number, not '{type(value).__name__}'"
    raise TypeError(message)


def iterable_values(value: ConfigValue) -> Iterable[ConfigValue]:
    """Iterate stored list values or mapping/string elements as the original caller did.

    Returns:
        The original iterable without copying its entries.

    Raises:
        TypeError: The persisted value cannot be iterated.
    """
    if isinstance(value, (list, dict, str, bytes)):
        return value
    message = f"'{type(value).__name__}' object is not iterable"
    raise TypeError(message)
