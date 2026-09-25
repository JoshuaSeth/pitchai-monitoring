# Copyright (c) 2026 PitchAI. All rights reserved.
"""Compare sampled and current provider capacity windows."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from .value_parsing import integer, isoformat, number, parse_datetime

if TYPE_CHECKING:
    from datetime import datetime

    from .models import CapacityAccount, SampleWindow, UsageSampleAccount


def current_window_rates(
    accounts: list[CapacityAccount],
    *,
    now: datetime,
    window_key: str,
) -> list[float]:
    """Return average-to-date burn rates for valid current windows."""
    rates: list[float] = []
    for account in accounts:
        rate = _current_window_rate(account, now=now, window_key=window_key)
        if rate is not None:
            rates.append(rate)
    return rates


def _current_window_rate(
    account: CapacityAccount,
    *,
    now: datetime,
    window_key: str,
) -> float | None:
    if not account.get("enabled") or account.get("auth_valid") is not True:
        return None
    if account.get("stale") or window_key not in {"five_hour", "weekly"}:
        return None
    window = account["five_hour"] if window_key == "five_hour" else account["weekly"]
    if window.get("reported") is not True:
        return None
    used = number(window.get("used_percent"))
    reset_at = parse_datetime(window.get("reset_at"))
    window_seconds = integer(window.get("window_seconds")) or 18_000
    if used is None or reset_at is None:
        return None
    started_at = reset_at - timedelta(seconds=window_seconds)
    elapsed_hours = (now - started_at).total_seconds() / 3600.0
    if 1 / 12 <= elapsed_hours <= window_seconds / 3600.0 + 0.25:
        return max(0.0, used / elapsed_hours)
    return None


def sample_window(
    account: UsageSampleAccount,
    *,
    at: datetime,
    key: str,
) -> SampleWindow | None:
    """Read one sampled window, including the legacy weekly representation.

    Returns:
        The resulting value.

    """
    prefix = "five" if key == "five_hour" else "weekly"
    used = number(account.get(f"{prefix}_used_percent"))
    reset_at = parse_datetime(account.get(f"{prefix}_reset_at"))
    if used is not None and reset_at is not None:
        return {"used_percent": used, "reset_at": isoformat(reset_at)}
    if key != "weekly":
        return None
    return _legacy_weekly_window(account, at=at)


def _legacy_weekly_window(
    account: UsageSampleAccount,
    *,
    at: datetime,
) -> SampleWindow | None:
    legacy_used = number(account.get("five_used_percent"))
    legacy_reset = parse_datetime(account.get("five_reset_at"))
    if legacy_used is not None and legacy_reset is not None and legacy_reset - at > timedelta(hours=6):
        return {"used_percent": legacy_used, "reset_at": isoformat(legacy_reset)}
    return None
