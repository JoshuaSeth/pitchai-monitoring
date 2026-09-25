# Copyright (c) 2026 PitchAI. All rights reserved.
"""Select the provider capacity window used by runout forecasts."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import CapacityAccount, CapacityBasis, CapacityWindow


def select_capacity_basis(accounts: list[CapacityAccount]) -> CapacityBasis:
    """Choose the best-reported capacity window for eligible accounts.

    Returns:
        The resulting value.

    """
    enabled_accounts = (account for account in accounts if account.get("enabled"))
    valid_accounts = (
        account
        for account in enabled_accounts
        if account.get("auth_valid") is True
    )
    fresh_accounts = (
        account for account in valid_accounts if not account.get("stale")
    )
    eligible = list(fresh_accounts)
    counts = _window_counts(eligible)
    key = _basis_key(counts, eligible_count=len(eligible))
    reporting = counts.get(key, 0) if key is not None else 0
    return {
        "key": key,
        "label": window_label(key),
        "reporting_accounts": reporting,
        "eligible_accounts": len(eligible),
        "measurement_status": _measurement_status(
            key,
            reporting=reporting,
            eligible_count=len(eligible),
        ),
    }


def measured_accounts(
    accounts: list[CapacityAccount],
    *,
    window_key: str,
) -> list[CapacityAccount]:
    """Return eligible accounts with a reported value for the chosen window."""
    measured: list[CapacityAccount] = []
    for account in accounts:
        if not account.get("enabled") or account.get("auth_valid") is not True:
            continue
        if account.get("stale"):
            continue
        window = capacity_window(account, window_key)
        if window["reported"] and window["remaining_percent"] is not None:
            measured.append(account)
    return measured


def capacity_window(account: CapacityAccount, key: str) -> CapacityWindow:
    """Return the named normalized provider capacity window.

    Raises:
        ValueError: If a value violates the required contract.

    """
    if key == "five_hour":
        return account["five_hour"]
    if key == "weekly":
        return account["weekly"]
    msg = f"unsupported capacity window: {key}"
    raise ValueError(msg)


def window_label(key: str | None) -> str:
    """Return the operator-facing label for one capacity basis."""
    if key == "five_hour":
        return "Five-hour"
    if key == "weekly":
        return "Weekly"
    return "Reported-window"


def _window_counts(accounts: list[CapacityAccount]) -> dict[str, int]:
    counts = {"five_hour": 0, "weekly": 0}
    for key in counts:
        for account in accounts:
            window = capacity_window(account, key)
            if window["reported"] and window["remaining_percent"] is not None:
                counts[key] += 1
    return counts


def _basis_key(counts: dict[str, int], *, eligible_count: int) -> str | None:
    short_window_minimum = max(1, math.ceil(eligible_count / 2))
    if counts["five_hour"] >= short_window_minimum:
        return "five_hour"
    if counts["weekly"]:
        return "weekly"
    if counts["five_hour"]:
        return "five_hour"
    return None


def _measurement_status(
    key: str | None,
    *,
    reporting: int,
    eligible_count: int,
) -> str:
    if key is None:
        return "unavailable"
    return "complete" if reporting == eligible_count else "partial"
