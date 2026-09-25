# Copyright (c) 2026 PitchAI. All rights reserved.
"""Validate and sanitize primitive guardian model values."""

from __future__ import annotations

import re
from datetime import UTC as DATETIME_UTC
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .json_contract import JsonValue

UTC = DATETIME_UTC
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


class PayloadError(RuntimeError):
    """A broker or provider payload did not satisfy the protection contract."""


def utc_now() -> datetime:
    """Return the current timezone-aware UTC instant.

    Raises:
        RuntimeError: If the system clock violates the UTC contract.

    """
    current_time = datetime.now(tz=UTC)
    if current_time.utcoffset() != UTC.utcoffset(current_time):
        msg = "system clock did not return a canonical UTC instant"
        raise RuntimeError(msg)
    return current_time


def utc_iso(value: datetime) -> str:
    """Serialize one timezone-aware instant as canonical UTC RFC3339 text.

    Returns:
        The resulting text.

    Raises:
        ValueError: If a value violates the required contract.

    """
    if value.tzinfo is None:
        msg = "UTC timestamp must be timezone-aware"
        raise ValueError(msg)
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_timestamp(value: JsonValue, *, field_name: str) -> datetime:
    """Parse one required timezone-aware RFC3339 timestamp.

    Returns:
        The resulting value.

    Raises:
        PayloadError: If provider data violates the payload contract.

    """
    if not isinstance(value, str) or not value.strip():
        msg = f"{field_name} must be a non-empty RFC3339 timestamp"
        raise PayloadError(msg)
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        msg = f"{field_name} is not a valid RFC3339 timestamp"
        raise PayloadError(msg) from exc
    if parsed.tzinfo is None:
        msg = f"{field_name} must include a timezone"
        raise PayloadError(msg)
    return parsed.astimezone(UTC)


def safe_label(value: JsonValue) -> str:
    """Validate and bound one account or provider label.

    Returns:
        The resulting text.

    Raises:
        PayloadError: If provider data violates the payload contract.

    """
    if not isinstance(value, str) or not value.strip():
        msg = "broker account label must be present"
        raise PayloadError(msg)
    normalized = _CONTROL_CHARACTERS.sub(" ", value.strip())
    return normalized[:240]
