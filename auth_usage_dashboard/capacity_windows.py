# Copyright (c) 2026 PitchAI. All rights reserved.
"""Parse and aggregate provider capacity windows."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from .value_parsing import integer, optional_isoformat, parse_datetime, percent

if TYPE_CHECKING:
    from datetime import datetime

    from .json_contract import JsonObject, JsonValue
    from .models import CapacityAccount, CapacityWindow, WindowAggregate

WindowKey = Literal["five_hour", "weekly"]


def parse_window(
    value: JsonValue,
    *,
    now: datetime,
    default_seconds: int,
) -> CapacityWindow:
    """Normalize one provider window without inventing unreported values.

    Returns:
        The resulting value.

    """
    reported = isinstance(value, dict)
    window = value if reported else {}
    used = percent(window.get("used_percent"))
    remaining = None if used is None else round(max(0.0, 100.0 - used), 2)
    reset_at = parse_datetime(window.get("reset_at"))
    reset_in = None if reset_at is None else max(0, int((reset_at - now).total_seconds()))
    seconds = _window_seconds(
        window,
        reported=reported,
        default_seconds=default_seconds,
    )
    return {
        "reported": reported,
        "used_percent": used,
        "remaining_percent": remaining,
        "reset_at": optional_isoformat(reset_at),
        "reset_in_seconds": reset_in,
        "window_seconds": seconds,
    }


def _window_seconds(
    window: JsonObject,
    *,
    reported: bool,
    default_seconds: int,
) -> int | None:
    if not reported:
        return None
    return integer(window.get("limit_window_seconds"), minimum=1) or default_seconds


def named_rate_limit_windows(
    rate_limit: JsonObject,
) -> dict[WindowKey, JsonObject | None]:
    """Classify provider windows by duration rather than response order.

    Returns:
        The resulting collection.

    """
    named: dict[WindowKey, JsonObject | None] = {
        "five_hour": None,
        "weekly": None,
    }
    for field in ("primary_window", "secondary_window"):
        window = rate_limit.get(field)
        if isinstance(window, dict):
            _classify_window(named, window)
    return named


def _classify_window(
    named: dict[WindowKey, JsonObject | None],
    window: JsonObject,
) -> None:
    seconds = integer(window.get("limit_window_seconds"), minimum=1)
    is_five_hour = seconds is not None and 4 * 60 * 60 <= seconds <= 6 * 60 * 60
    is_weekly = seconds is not None and seconds >= 6 * 24 * 60 * 60
    if is_five_hour and named["five_hour"] is None:
        named["five_hour"] = window
    elif is_weekly and named["weekly"] is None:
        named["weekly"] = window


def window_aggregate(
    accounts: list[CapacityAccount],
    *,
    key: WindowKey,
) -> WindowAggregate:
    """Aggregate known remaining capacity without treating unknown as zero.

    Returns:
        The resulting value.

    """
    measured: list[CapacityAccount] = []
    for account in accounts:
        if account["auth_valid"] is not True or account["stale"]:
            continue
        window = account[key]
        remaining = window.get("remaining_percent")
        if window.get("reported") is True and isinstance(remaining, (int, float)):
            measured.append(account)
    remaining_points = _remaining_points(measured, key=key)
    maximum_points = float(len(measured) * 100)
    return {
        "measurement_status": _measurement_status(
            measured_count=len(measured),
            account_count=len(accounts),
        ),
        "reporting_accounts": len(measured),
        "unknown_accounts": len(accounts) - len(measured),
        "remaining_points": round(remaining_points, 1) if measured else None,
        "maximum_known_points": round(maximum_points, 1) if measured else None,
        "remaining_percent": (round(remaining_points / maximum_points * 100.0, 1) if measured else None),
    }


def _remaining_points(accounts: list[CapacityAccount], *, key: WindowKey) -> float:
    total = 0.0
    for account in accounts:
        remaining = account[key]["remaining_percent"]
        if remaining is not None:
            total += remaining
    return total


def _measurement_status(*, measured_count: int, account_count: int) -> str:
    if not measured_count:
        return "unavailable"
    return "partial" if measured_count < account_count else "complete"


def window_label(key: str | None) -> str | None:
    """Return the snapshot label for one measured window."""
    if key == "five_hour":
        return "Five-hour"
    if key == "weekly":
        return "Weekly"
    return None
