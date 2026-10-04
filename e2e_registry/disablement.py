# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared disabled-until parsing for the registry API and dashboard."""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, date, datetime
from typing import Final

_EMPTY: Final[str] = ""


type DisablementValue = str | int | float | None


def parse_disabled_until(value: DisablementValue) -> float | None:
    """Parse numeric, ISO datetime and ISO date values with the original precedence.

    Returns:
        A positive Unix timestamp or ``None`` for empty/nonpositive values.

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
        # Let the standard parser raise its historical ValueError text.  The
        # app endpoint prefixes that message with ``invalid_until:``.
        parsed_date = date.fromisoformat(text)
        parsed = datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()
