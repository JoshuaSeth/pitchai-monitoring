# Copyright (c) 2026 PitchAI. All rights reserved.
"""Provide shared deterministic forecast schedule calculations."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from .models import CapacityAccount, CapacityWindow


def primary_window(
    account: CapacityAccount,
    window_key: str | None,
) -> CapacityWindow | None:
    """Return the selected account capacity window when supported."""
    if window_key == "five_hour":
        return account["five_hour"]
    if window_key == "weekly":
        return account["weekly"]
    return None


def scheduled_resets(
    *,
    first_reset: datetime | None,
    window_seconds: int,
    now: datetime,
    horizon_end: datetime,
) -> list[datetime]:
    """Return recurring provider resets inside one forecast horizon."""
    if first_reset is None or window_seconds <= 0:
        return []
    candidate = first_reset
    while candidate <= now:
        candidate += timedelta(seconds=window_seconds)
    resets: list[datetime] = []
    while candidate <= horizon_end:
        resets.append(candidate)
        candidate += timedelta(seconds=window_seconds)
    return resets


def current_pool(accounts: list[CapacityAccount]) -> tuple[int, bool]:
    """Count fresh usable accounts and detect stale enabled accounts.

    Returns:
        The resulting collection.

    """
    usable_now = 0
    stale_enabled = False
    for account in accounts:
        if account["selectable_now"] and not account["stale"]:
            usable_now += 1
        if account["enabled"] and account["stale"]:
            stale_enabled = True
    return usable_now, stale_enabled


def forecast_confidence(
    *,
    measured_windows: int,
    unknown_windows: int,
    stale_enabled: bool,
) -> str:
    """Classify deterministic forecast confidence from measurement coverage.

    Returns:
        The resulting text.

    """
    if not measured_windows:
        return "unavailable"
    if unknown_windows or stale_enabled:
        return "partial"
    return "high"
