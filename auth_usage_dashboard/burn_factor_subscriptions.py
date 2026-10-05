# Copyright (c) 2026 PitchAI. All rights reserved.
"""Subscription access ends for the burn factor, keyed by account email.

Only verified non-renewing subscriptions end: an exact ``access_ends_at`` wins;
a date-only ``access_ends_on`` stays active through that local day and ends at
the next local midnight, matching the subscription section's own rule.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .timeseries_types import optional_object, text_value

if TYPE_CHECKING:
    from .timeseries_types import JsonObject

ENDING_STATES = frozenset({"active_until_end", "access_ended", "inactive"})
_DEFAULT_ZONE = "Europe/Berlin"
ENDED_LONG_AGO = datetime(1970, 1, 1, tzinfo=UTC)


def _zone(name: str | None) -> ZoneInfo:
    with suppress(ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(name or _DEFAULT_ZONE)
    return ZoneInfo(_DEFAULT_ZONE)


def _end_instant(row: JsonObject, zone: ZoneInfo) -> datetime | None:
    exact_text = text_value(row.get("access_ends_at"))
    if exact_text is not None:
        with suppress(ValueError):
            exact = datetime.fromisoformat(exact_text)
            if exact.tzinfo is not None:
                return exact.astimezone(UTC)
    day_text = text_value(row.get("access_ends_on"))
    if day_text is None:
        return None
    with suppress(ValueError):
        next_day = date.fromisoformat(day_text) + timedelta(days=1)
        return datetime.combine(next_day, time(0), tzinfo=zone).astimezone(UTC)
    return None


def subscription_ends(snapshot: JsonObject) -> dict[str, datetime]:
    """Return lower-case account email → access end (UTC) for subscriptions that end.

    Returns:
        Only rows whose verified state says access ends or has ended and whose end is known.
    """
    zone = _zone(text_value(snapshot.get("timezone")))
    rows = snapshot.get("accounts")
    ends: dict[str, datetime] = {}
    for raw in rows if isinstance(rows, list) else []:
        row = optional_object(raw)
        email = text_value(row.get("email"))
        if email is None or row.get("access_state") not in ENDING_STATES:
            continue
        instant = _end_instant(row, zone)
        if instant is None and row.get("access_state") != "active_until_end":
            instant = ENDED_LONG_AGO
        if instant is not None:
            ends[email.lower()] = instant
    return ends
