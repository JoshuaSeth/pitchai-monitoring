# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing inventory expiry and heartbeat time parsing."""

from __future__ import annotations

import logging
from contextlib import suppress
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if TYPE_CHECKING:
    from datetime import tzinfo

    from .config_values import ConfigValue

LOGGER = logging.getLogger("service-monitoring")
_LAST_HOUR = 23
_LAST_MINUTE = 59


def parse_disabled_until_ts(value: ConfigValue) -> float | None:
    """Return the existing positive numeric or ISO calendar timestamp.

    Naive calendar input is UTC; numeric zero/negative values mean no expiry.
    Calendar values retain their original pre-epoch behavior.

    Returns:
        The existing absolute timestamp or absent numeric expiry.

    Raises:
        ValueError: The input is neither a numeric nor an ISO calendar value.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        return timestamp if timestamp > 0 else None
    text = str(value or "").strip()
    if not text:
        return None
    with suppress(ValueError):
        timestamp = float(text)
        return timestamp if timestamp > 0 else None
    parsed = _calendar_timestamp(text)
    if parsed is not None:
        return parsed
    message = f"Invalid disabled_until value {value!r}; expected unix timestamp or ISO-8601 datetime/date"
    raise ValueError(message)


def _calendar_timestamp(text: str) -> float | None:
    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    # These are separate format attempts at the configuration input boundary.
    with suppress(ValueError):
        observed = datetime.fromisoformat(iso_text)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        return observed.timestamp()
    with suppress(ValueError):
        day = date.fromisoformat(text)
        return datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()
    return None


def parse_hhmm(value: ConfigValue) -> time:
    """Return the existing hour/minute value without accepting extra fields.

    Raises:
        ValueError: The configured value is not a valid hour and minute.
    """
    text = str(value or "").strip()
    message = f"Invalid time (expected HH:MM): {value!r}"
    if not text or ":" not in text:
        raise ValueError(message)
    hour_text, minute_text = text.split(":", 1)
    hour, minute = int(hour_text), int(minute_text)
    if not (0 <= hour <= _LAST_HOUR and 0 <= minute <= _LAST_MINUTE):
        raise ValueError(message)
    return time(hour=hour, minute=minute)


def load_timezone(name: str) -> tzinfo:
    """Return the configured zone, preserving the logged UTC fallback."""
    cleaned = (name or "").strip()
    if not cleaned or cleaned.upper() == "UTC":
        return UTC
    with suppress(ZoneInfoNotFoundError):
        return ZoneInfo(cleaned)
    LOGGER.warning("Timezone not found; falling back to UTC tz=%s", cleaned)
    return UTC
