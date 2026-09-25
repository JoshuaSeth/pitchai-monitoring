# Copyright (c) 2026 PitchAI. All rights reserved.
"""Calculate dashboard summary and source freshness counters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .capacity_snapshot_types import SnapshotStats
from .capacity_windows import window_aggregate
from .value_parsing import parse_datetime

if TYPE_CHECKING:
    from datetime import datetime

    from .models import CapacityAccount, CapacityEvent, StatusCounts, WindowAggregates


def snapshot_stats(
    accounts: list[CapacityAccount],
    events: list[CapacityEvent],
) -> SnapshotStats:
    """Calculate reusable counters from normalized account state.

    Returns:
        The resulting value.

    """
    enabled_accounts: list[CapacityAccount] = []
    probe_values: list[datetime] = []
    for account in accounts:
        if account["enabled"]:
            enabled_accounts.append(account)
        probe_at = parse_datetime(account.get("last_probe_at"))
        if probe_at is not None:
            probe_values.append(probe_at)
    stale_count = sum(1 for account in enabled_accounts if account["stale"])
    analytics_stale_count = sum(
        1 for account in enabled_accounts if account["token_usage"]["stale"] or account["reset_credits"]["stale"]
    )
    fresh_usable_count = sum(1 for account in enabled_accounts if account["selectable_now"] and not account["stale"])
    aggregates: WindowAggregates = {
        "five_hour": window_aggregate(enabled_accounts, key="five_hour"),
        "weekly": window_aggregate(enabled_accounts, key="weekly"),
    }
    return SnapshotStats(
        enabled_accounts,
        stale_count,
        analytics_stale_count,
        fresh_usable_count,
        _status_counts(accounts),
        min(probe_values, default=None),
        max(probe_values, default=None),
        _next_useful_event(events),
        aggregates,
    )


def _status_counts(accounts: list[CapacityAccount]) -> StatusCounts:
    counts: StatusCounts = {
        "available": 0,
        "five_hour_limited": 0,
        "weekly_limited": 0,
        "auth_invalid": 0,
        "disabled": 0,
        "unknown": 0,
    }
    for account in accounts:
        status = account["status"]
        if status == "available":
            counts["available"] += 1
        elif status == "five_hour_limited":
            counts["five_hour_limited"] += 1
        elif status == "weekly_limited":
            counts["weekly_limited"] += 1
        elif status == "auth_invalid":
            counts["auth_invalid"] += 1
        elif status == "disabled":
            counts["disabled"] += 1
        else:
            counts["unknown"] += 1
    return counts


def _next_useful_event(events: list[CapacityEvent]) -> CapacityEvent | None:
    for event in events:
        if event["restores_selectability"]:
            return event
    return events[0] if events else None
