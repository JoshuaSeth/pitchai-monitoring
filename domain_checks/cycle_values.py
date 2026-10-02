# Copyright (c) 2026 PitchAI. All rights reserved.
"""Numeric boundaries shared by monitor configuration and retained state."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .event_bus_delivery import JsonValue

type NumericInput = JsonValue | bytes


def required_int(value: NumericInput) -> int:
    """Convert scalar input without silently defaulting an invalid setting.

    Returns:
        The same integer conversion used by the existing monitor.

    Raises:
        TypeError: The input is not an integer-convertible scalar.
    """
    if isinstance(value, (str, bytes, int, float)):
        return int(value)
    message = f"integer setting cannot use {type(value).__name__}"
    raise TypeError(message)


def required_float(value: NumericInput) -> float:
    """Convert scalar input while retaining the existing float semantics.

    Returns:
        The converted value, including existing nonfinite scalar behavior.

    Raises:
        TypeError: The input is not a float-convertible scalar.
    """
    if isinstance(value, (str, bytes, int, float)):
        return float(value)
    message = f"float setting cannot use {type(value).__name__}"
    raise TypeError(message)


def bool_field(state: Mapping[str, JsonValue], key: str, *, default: bool) -> bool:
    """Read an actual boolean field from retained state.

    Returns:
        The input boolean, or the caller's fallback for every other value.
    """
    value = state.get(key)
    return value if isinstance(value, bool) else bool(default)


def coerce_int(value: NumericInput, *, default: int = 0) -> int:
    """Apply the monitor's permissive integer fallback at state boundaries.

    Returns:
        A converted scalar or the caller's default on conversion failure.
    """
    # Malformed retained-state input uses the existing caller-owned fallback.
    with suppress(TypeError, ValueError, OverflowError):
        return required_int(value)
    return int(default)


def coerce_float(value: NumericInput, *, default: float = 0.0) -> float:
    """Apply the monitor's permissive float fallback at state boundaries.

    Returns:
        A converted scalar or the caller's default on conversion failure.
    """
    # Limit fallback to conversion failures at the configuration/state boundary.
    with suppress(TypeError, ValueError, OverflowError):
        return required_float(value)
    return float(default)


def coerce_optional_float(value: NumericInput) -> float | None:
    """Read an optional threshold without inventing one for invalid input.

    Returns:
        A converted scalar, or None for absent or invalid input.
    """
    with suppress(TypeError, ValueError, OverflowError):
        return required_float(value)
    return None
