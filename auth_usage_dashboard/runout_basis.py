# Copyright (c) 2026 PitchAI. All rights reserved.
"""Selection of the provider capacity window that drives runout forecasts."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .history_values import eligible_accounts

if TYPE_CHECKING:
    from .timeseries_types import JsonObject

FORECAST_WINDOW_KEYS = ("five_hour", "weekly")


def select_capacity_basis(accounts: list[JsonObject]) -> JsonObject:
    """Choose the reported window that best represents selectable capacity.

    The five-hour window wins when at least half of the eligible accounts
    report it; otherwise any weekly coverage wins over partial five-hour data.

    Returns:
        The chosen window key, its label, and its reporting coverage.
    """
    eligible = eligible_accounts(accounts)
    counts = {key: _reporting_count(eligible, key=key) for key in FORECAST_WINDOW_KEYS}
    minimum_short_window_coverage = max(1, math.ceil(len(eligible) / 2))
    key = _basis_key(counts, minimum_short_window_coverage=minimum_short_window_coverage)
    reporting = counts.get(key, 0) if key is not None else 0
    return {
        "key": key,
        "label": window_label(key),
        "reporting_accounts": reporting,
        "eligible_accounts": len(eligible),
        "measurement_status": _measurement_status(key, reporting=reporting, eligible=len(eligible)),
    }


def account_window(account: JsonObject, key: str) -> JsonObject:
    """Return one provider window of an account, treating absence as empty.

    Returns:
        The window object, or an empty object when the account omits it.

    Raises:
        TypeError: If the account carries a non-object value for the window.
    """
    window = account.get(key, {})
    if isinstance(window, dict):
        return window
    message = f"account {key} window must be a JSON object"
    raise TypeError(message)


def reports_remaining(account: JsonObject, key: str) -> bool:
    """Return whether a window is reported together with a numeric remainder."""
    window = account_window(account, key)
    return window.get("reported") is True and isinstance(window.get("remaining_percent"), (int, float))


def window_label(key: str | None) -> str:
    """Return the display label of one forecast window key."""
    if key == "five_hour":
        return "Five-hour"
    if key == "weekly":
        return "Weekly"
    return "Reported-window"


def _reporting_count(accounts: list[JsonObject], *, key: str) -> int:
    reporting = [account for account in accounts if reports_remaining(account, key)]
    return len(reporting)


def _basis_key(counts: dict[str, int], *, minimum_short_window_coverage: int) -> str | None:
    if counts["five_hour"] >= minimum_short_window_coverage:
        return "five_hour"
    if counts["weekly"]:
        return "weekly"
    if counts["five_hour"]:
        return "five_hour"
    return None


def _measurement_status(key: str | None, *, reporting: int, eligible: int) -> str:
    if key is None:
        return "unavailable"
    return "complete" if reporting == eligible else "partial"
