# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared disabled-until parsing for the registry API and dashboard."""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, date, datetime
from typing import Final

_EMPTY: Final[str] = ""


class InvalidDisablementError(ValueError):
    """A populated disabled-until value cannot be converted to UTC epoch seconds."""


type DisablementValue = str | int | float | None


def parse_disabled_until(value: DisablementValue) -> float | None:
    """Parse numeric, ISO datetime and ISO date values with the original precedence.

    Returns:
        A positive Unix timestamp or ``None`` for empty/nonpositive values.

    Raises:
        InvalidDisablementError: The populated value is not a valid numeric/date value.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        return timestamp if timestamp > 0 else None
    text = str(value or _EMPTY).strip()
    if not text:
        return None
    timestamp: float | None = None
    with suppress(ValueError):
        timestamp = float(text)
    if timestamp is not None:
        return timestamp if timestamp > 0 else None

    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    parsed: datetime | None = None
    with suppress(ValueError):
        parsed = datetime.fromisoformat(iso_text)
    if parsed is None:
        parsed_date: date | None = None
        with suppress(ValueError):
            parsed_date = date.fromisoformat(text)
        if parsed_date is None:
            message = f"Invalid isoformat value: {text}"
            raise InvalidDisablementError(message)
        parsed = datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()
