# Copyright (c) 2026 PitchAI. All rights reserved.
"""Provider quota windows: identification, rendering, and fleet aggregation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .capacity_values import bounded_integer, isoformat, parse_timestamp
from .timeseries_types import optional_object

if TYPE_CHECKING:
    from datetime import datetime

    from .timeseries_types import JsonObject

_FIVE_HOUR_DEFAULT_SECONDS = 5 * 60 * 60
_WEEKLY_DEFAULT_SECONDS = 7 * 24 * 60 * 60
_SHORT_WINDOW_MIN_SECONDS = 4 * 60 * 60
_SHORT_WINDOW_MAX_SECONDS = 6 * 60 * 60
_LONG_WINDOW_MIN_SECONDS = 6 * 24 * 60 * 60


def account_windows(usage: JsonObject, *, now: datetime) -> tuple[JsonObject, JsonObject]:
    """Identify and render the five-hour and weekly windows in one usage summary.

    Provider windows are named by their declared length, never by their field
    position, so a weekly-only account never reports a fake five-hour window.

    Returns:
        The rendered five-hour window followed by the rendered weekly window.
    """
    rate_limit = optional_object(usage.get("rate_limit"))
    five_hour: JsonObject | None = None
    weekly: JsonObject | None = None
    for field in ("primary_window", "secondary_window"):
        window = rate_limit.get(field)
        if not isinstance(window, dict):
            continue
        seconds = bounded_integer(window.get("limit_window_seconds"), minimum=1)
        if seconds is None:
            continue
        if five_hour is None and _SHORT_WINDOW_MIN_SECONDS <= seconds <= _SHORT_WINDOW_MAX_SECONDS:
            five_hour = window
        elif weekly is None and seconds >= _LONG_WINDOW_MIN_SECONDS:
            weekly = window
    return (
        _rendered_window(five_hour, now=now, default_seconds=_FIVE_HOUR_DEFAULT_SECONDS),
        _rendered_window(weekly, now=now, default_seconds=_WEEKLY_DEFAULT_SECONDS),
    )


def _rendered_window(window: JsonObject | None, *, now: datetime, default_seconds: int) -> JsonObject:
    fields = window if window is not None else {}
    raw_used = fields.get("used_percent")
    used: float | None = None
    if isinstance(raw_used, (int, float)) and not isinstance(raw_used, bool):
        used = round(min(100.0, max(0.0, float(raw_used))), 2)
    remaining = None if used is None else round(max(0.0, 100.0 - used), 2)
    reset_at = parse_timestamp(fields.get("reset_at"))
    reset_in = None if reset_at is None else max(0, int((reset_at - now).total_seconds()))
    seconds: int | None = None
    if window is not None:
        seconds = bounded_integer(fields.get("limit_window_seconds"), minimum=1) or default_seconds
    return {
        "reported": window is not None,
        "used_percent": used,
        "remaining_percent": remaining,
        "reset_at": isoformat(reset_at),
        "reset_in_seconds": reset_in,
        "window_seconds": seconds,
    }


def window_aggregate(accounts: list[JsonObject], *, key: str) -> JsonObject:
    """Sum the remaining capacity that fresh auth-valid accounts report for one window.

    Returns:
        Measured remaining points against the maximum known for that window.
    """
    remaining_values: list[float] = []
    for account in accounts:
        window = optional_object(account[key])
        remaining = window.get("remaining_percent")
        measured = account["auth_valid"] is True and not account["stale"] and window.get("reported") is True
        if measured and isinstance(remaining, (int, float)):
            remaining_values.append(float(remaining))
    reporting = len(remaining_values)
    remaining_points = sum(remaining_values)
    maximum_points = float(reporting * 100)
    if not reporting:
        measurement_status = "unavailable"
    elif reporting < len(accounts):
        measurement_status = "partial"
    else:
        measurement_status = "complete"
    return {
        "measurement_status": measurement_status,
        "reporting_accounts": reporting,
        "unknown_accounts": len(accounts) - reporting,
        "remaining_points": round(remaining_points, 1) if reporting else None,
        "maximum_known_points": round(maximum_points, 1) if reporting else None,
        "remaining_percent": round(remaining_points / maximum_points * 100.0, 1) if reporting else None,
    }
