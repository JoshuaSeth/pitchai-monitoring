# Copyright (c) 2026 PitchAI. All rights reserved.
"""Timestamp and lenient JSON value coercion for redacted usage samples."""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue


def isoformat(value: datetime) -> str:
    """Return one timestamp as UTC ISO 8601 text with a ``Z`` suffix."""
    utc_text = value.astimezone(UTC).isoformat()
    return utc_text.replace("+00:00", "Z")


def parse_datetime(value: JsonValue) -> datetime | None:
    """Parse ISO 8601 text into a UTC timestamp.

    Every ``Z`` is rewritten to ``+00:00`` before parsing, which keeps the
    historical acceptance set of the sample store intact.

    Returns:
        The UTC timestamp, or None for absent, blank, or unparseable values.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    parsed: datetime | None = None
    with suppress(ValueError):
        parsed = datetime.fromisoformat(normalized).astimezone(UTC)
    return parsed


def floor_hour(value: datetime) -> datetime:
    """Return the UTC start of the hour that contains one timestamp."""
    utc_value = value.astimezone(UTC)
    return utc_value.replace(minute=0, second=0, microsecond=0)


def sample_accounts(sample: JsonObject) -> JsonObject:
    """Return the per-account section of one usage sample.

    Returns:
        The account mapping, or an empty mapping when the sample has none.

    Raises:
        TypeError: If the sample carries a non-object account section.
    """
    accounts = sample.get("accounts", {})
    if isinstance(accounts, dict):
        return accounts
    message = "usage sample accounts must be a JSON object"
    raise TypeError(message)


def eligible_accounts(accounts: list[JsonObject]) -> list[JsonObject]:
    """Return enabled, auth-valid, fresh accounts in their original order."""
    enabled = [account for account in accounts if account.get("enabled")]
    authorized = [account for account in enabled if account.get("auth_valid") is True]
    return [account for account in authorized if not account.get("stale")]


def iterated_items(value: JsonValue, *, description: str) -> list[JsonValue]:
    """Return what Python iteration yields for one JSON value.

    Arrays yield their elements, objects their keys, and text its characters.

    Returns:
        The iterated items in order.

    Raises:
        TypeError: If the value is null, a boolean, or a number.
    """
    if isinstance(value, (list, dict, str)):
        items: list[JsonValue] = [*value]
        return items
    message = f"{description} must be iterable"
    raise TypeError(message)


def sample_number(value: JsonValue) -> float | None:
    """Return a JSON number as float while excluding booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def sample_integer(value: JsonValue) -> int | None:
    """Coerce a JSON scalar with ``int()`` and keep only non-negative results.

    Returns:
        The non-negative integer, or None for booleans, containers, null,
        unparseable text, and negative values.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    parsed: int | None = None
    with suppress(ValueError):
        parsed = int(value)
    if parsed is None or parsed < 0:
        return None
    return parsed


def whole_number(value: JsonValue) -> int:
    """Coerce a JSON scalar with ``int()``.

    Returns:
        The integer value of a number, boolean, or integral text.

    Raises:
        TypeError: If the value is null, an array, or an object.
    """
    if isinstance(value, (int, float, str)):
        return int(value)
    message = f"expected a number or numeric text, not {type(value).__name__}"
    raise TypeError(message)


def real_number(value: JsonValue) -> float:
    """Coerce a JSON scalar with ``float()``.

    Returns:
        The float value of a number, boolean, or numeric text.

    Raises:
        TypeError: If the value is null, an array, or an object.
    """
    if isinstance(value, (int, float, str)):
        return float(value)
    message = f"expected a number or numeric text, not {type(value).__name__}"
    raise TypeError(message)
