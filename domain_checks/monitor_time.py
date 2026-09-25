# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict wall-clock and timezone parsing for monitor schedules."""

from __future__ import annotations

from datetime import UTC, time
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from domain_checks.monitor_values import json_int

if TYPE_CHECKING:
    from datetime import tzinfo

    from domain_checks.types import JsonValue

_LAST_HOUR = 23
_LAST_MINUTE = 59


def parse_hhmm(value: JsonValue) -> time:
    """Parse a strict HH:MM wall-clock value.

    Returns:
        The parsed wall-clock time.

    Raises:
        ValueError: The value is not a valid HH:MM time.
    """
    text = str(value or "").strip()
    if ":" not in text:
        message = f"Invalid time (expected HH:MM): {value!r}"
        raise ValueError(message)
    hour_text, minute_text = text.split(":", 1)
    hour = json_int(hour_text)
    minute = json_int(minute_text)
    if 0 <= hour <= _LAST_HOUR and 0 <= minute <= _LAST_MINUTE:
        return time(hour=hour, minute=minute)
    message = f"Invalid time (expected HH:MM): {value!r}"
    raise ValueError(message)


def load_timezone(name: str) -> tzinfo:
    """Load a configured timezone, using UTC only for an absent UTC setting.

    Returns:
        The requested timezone implementation.

    Raises:
        ValueError: The timezone name is unknown.
    """
    cleaned = name.strip()
    if not cleaned or cleaned.upper() == "UTC":
        return UTC
    try:
        return ZoneInfo(cleaned)
    except ZoneInfoNotFoundError as exc:
        message = f"Unknown timezone: {cleaned}"
        raise ValueError(message) from exc
