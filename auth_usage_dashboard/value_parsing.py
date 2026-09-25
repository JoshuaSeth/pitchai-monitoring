# Copyright (c) 2026 PitchAI. All rights reserved.
"""Provide shared strict value parsing for dashboard boundaries."""

from __future__ import annotations

from datetime import UTC as DATETIME_UTC
from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .json_contract import JsonObject, JsonValue

UTC = DATETIME_UTC


def utc_now() -> datetime:
    """Return the current aware UTC timestamp.

    Raises:
        RuntimeError: If the system clock violates the UTC contract.

    """
    current_time = datetime.now(UTC)
    if current_time.utcoffset() != UTC.utcoffset(current_time):
        msg = "system clock did not return a canonical UTC timestamp"
        raise RuntimeError(msg)
    return current_time


def isoformat(value: datetime) -> str:
    """Format one timestamp as RFC3339 UTC.

    Returns:
        The resulting value.

    """
    normalized = value.astimezone(UTC)
    return normalized.isoformat().replace("+00:00", "Z")


def optional_isoformat(value: datetime | None) -> str | None:
    """Format one optional timestamp as RFC3339 UTC.

    Returns:
        The resulting value.

    """
    if value is None:
        return None
    return isoformat(value)


def parse_datetime(value: JsonValue) -> datetime | None:
    """Parse a timestamp string or positive Unix timestamp.

    Returns:
        The resulting value.

    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        try:
            return datetime.fromtimestamp(value, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip()).astimezone(UTC)
        except ValueError:
            return None
    return None


def parse_date(value: JsonValue) -> date | None:
    """Parse one ISO calendar date.

    Returns:
        The resulting value.

    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def percent(value: JsonValue) -> float | None:
    """Clamp one numeric percentage to the inclusive 0-100 range.

    Returns:
        The resulting value.

    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(min(100.0, max(0.0, float(value))), 2)


def number(value: JsonValue) -> float | None:
    """Return one non-boolean numeric value as a float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def integer(value: JsonValue, *, minimum: int = 0) -> int | None:
    """Parse one integer no smaller than the requested minimum.

    Returns:
        The resulting value.

    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        parsed = int(value)
    elif isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed >= minimum else None


def string(value: JsonValue) -> str | None:
    """Return one non-empty stripped string."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def limited_string(value: JsonValue, limit: int) -> str | None:
    """Return one stripped string bounded to the requested length."""
    text = string(value)
    return None if text is None else text[:limit]


def object_value(container: JsonObject, key: str) -> JsonObject:
    """Return a nested JSON object or an empty object when absent."""
    value = container.get(key)
    return value if isinstance(value, dict) else {}


def account_lookup_key(raw: JsonObject) -> str:
    """Return the broker label or opaque account ID used for probe errors."""
    metadata = object_value(raw, "metadata")
    return str(metadata.get("label") or metadata.get("account_id") or "")
