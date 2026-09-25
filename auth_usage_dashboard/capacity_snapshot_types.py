# Copyright (c) 2026 PitchAI. All rights reserved.
"""Define internal types used to assemble one dashboard snapshot."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, NotRequired, TypedDict

if TYPE_CHECKING:
    from datetime import datetime

    from .models import (
        CapacityAccount,
        CapacityBasis,
        CapacityEvent,
        CapacityForecast,
        DashboardWarning,
        HourlyUsageHistory,
        ResetBank,
        RunoutForecast,
        StatusCounts,
        UsageSample,
        WindowAggregates,
    )


class SnapshotArguments(TypedDict):
    """Declare the keyword contract accepted by snapshot construction."""

    now: datetime
    stale_after_seconds: int
    min_five_hour_remaining_percent: float
    analytics_stale_after_seconds: NotRequired[int]
    probe_errors: NotRequired[dict[str, str] | None]
    analytics_probe_errors: NotRequired[dict[str, str] | None]
    source_error: NotRequired[str | None]
    last_safe_probe_at: NotRequired[datetime | None]
    last_analytics_probe_at: NotRequired[datetime | None]
    probe_interval_seconds: NotRequired[int]
    analytics_probe_interval_seconds: NotRequired[int]
    usage_samples: NotRequired[list[UsageSample] | None]
    history_error: NotRequired[str | None]


class SnapshotOptions(NamedTuple):
    """Hold normalized snapshot inputs and explicit edge defaults."""

    now: datetime
    stale_after_seconds: int
    minimum_remaining: float
    analytics_stale_after_seconds: int
    probe_errors: dict[str, str]
    analytics_probe_errors: dict[str, str]
    source_error: str | None
    last_safe_probe_at: datetime | None
    last_analytics_probe_at: datetime | None
    probe_interval_seconds: int
    analytics_probe_interval_seconds: int
    usage_samples: list[UsageSample]
    history_error: str | None


class SnapshotParts(NamedTuple):
    """Hold independently derived dashboard payload sections."""

    capacity_basis: CapacityBasis
    forecasts: list[CapacityForecast]
    usage_history: HourlyUsageHistory
    reset_bank: ResetBank
    runout_forecast: RunoutForecast
    warnings: list[DashboardWarning]
    events: list[CapacityEvent]


class SnapshotStats(NamedTuple):
    """Hold aggregate counters and source freshness bounds."""

    enabled_accounts: list[CapacityAccount]
    stale_count: int
    analytics_stale_count: int
    fresh_usable_count: int
    status_counts: StatusCounts
    oldest_probe: datetime | None
    newest_probe: datetime | None
    next_useful: CapacityEvent | None
    window_aggregates: WindowAggregates
