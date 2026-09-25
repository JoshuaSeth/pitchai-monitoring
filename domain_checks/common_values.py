# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared strict scalar coercion for monitoring state boundaries."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain_checks.types import JsonValue


def coerce_optional_int(value: JsonValue, *, allow_bool: bool = False) -> int | None:
    """Convert an integer-like JSON scalar, optionally accepting booleans.

    Returns:
        The converted integer, or ``None`` when conversion is not possible.
    """
    if isinstance(value, bool) and not allow_bool:
        return None
    if not isinstance(value, bool | int | float | str):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None
