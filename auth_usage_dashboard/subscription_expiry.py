# Copyright (c) 2026 PitchAI. All rights reserved.
"""Preserve reviewed subscription expiry precision at the JSON boundary."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue

DEFAULT_TIMEZONE = "Europe/Berlin"


@dataclass(frozen=True)
class SubscriptionEnd:
    """A calendar date and optional verified instant, never a cancellation time."""

    day: str | None
    instant: datetime | None
    precision: Literal["date", "exact", "unknown", "invalid"]


def subscription_timezone(value: JsonValue) -> ZoneInfo | None:
    """Resolve a supported declared zone, retaining the legacy default when absent.

    Returns:
        A valid IANA timezone, or none for an explicitly unsupported declaration.
    """
    if value is None:
        return ZoneInfo(DEFAULT_TIMEZONE)
    if isinstance(value, str) and value:
        with suppress(ZoneInfoNotFoundError, ValueError):
            return ZoneInfo(value)
    return None


def subscription_end(row: JsonObject, *, zone: ZoneInfo) -> SubscriptionEnd:
    """Validate optional exact evidence against the stated local calendar date.

    Returns:
        Explicit invalid precision for malformed or inconsistent exact evidence.
    """
    raw_day = row.get("access_ends_on")
    day: date | None = None
    if isinstance(raw_day, str):
        with suppress(ValueError):
            day = date.fromisoformat(raw_day)
    day_text = day.isoformat() if day is not None else None
    raw_exact = row.get("access_ends_at")
    if raw_exact is None:
        return SubscriptionEnd(day_text, None, "date" if day else "unknown")
    exact: datetime | None = None
    if isinstance(raw_exact, str):
        with suppress(ValueError):
            exact = datetime.fromisoformat(raw_exact)
    if exact is None or exact.tzinfo is None or day is None or exact.astimezone(zone).date() != day:
        return SubscriptionEnd(day_text, None, "invalid")
    return SubscriptionEnd(day_text, exact, "exact")
