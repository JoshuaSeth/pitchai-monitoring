# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lenient readers for the untrusted JSON values found in broker state files."""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .timeseries_types import JsonValue


def isoformat(value: datetime | None) -> str | None:
    """Render an optional instant as UTC ISO-8601 text with a ``Z`` suffix.

    Returns:
        The normalized timestamp, or None when no instant is known.
    """
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: JsonValue) -> datetime | None:
    """Read a positive epoch number or ISO-8601 text as an aware UTC instant.

    Returns:
        The instant, or None for booleans, blanks, and unrepresentable values.
    """
    if isinstance(value, bool):
        return None
    parsed: datetime | None = None
    if isinstance(value, (int, float)) and value > 0:
        with suppress(OverflowError, OSError, ValueError):
            parsed = datetime.fromtimestamp(value, tz=UTC)
    elif isinstance(value, str) and value.strip():
        # Every "Z" becomes "+00:00", not only a trailing UTC designator; this
        # deliberately keeps the broker's long-standing acceptance of odd forms.
        utc_offset_text = value.strip().replace("Z", "+00:00")
        with suppress(ValueError):
            parsed = datetime.fromisoformat(utc_offset_text).astimezone(UTC)
    return parsed


def parse_day(value: JsonValue) -> date | None:
    """Read ISO-8601 calendar-date text.

    Returns:
        The calendar date, or None for absent or malformed text.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    with suppress(ValueError):
        return date.fromisoformat(value.strip())
    return None


def bounded_integer(value: JsonValue, *, minimum: int) -> int | None:
    """Coerce an integral number or numeric text and enforce a lower bound.

    Returns:
        The integer when it parses and reaches the minimum, otherwise None.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    parsed: int | None = None
    with suppress(ValueError):
        parsed = int(value)
    if parsed is None or parsed < minimum:
        return None
    return parsed
