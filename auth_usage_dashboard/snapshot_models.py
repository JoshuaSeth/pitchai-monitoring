# Copyright (c) 2026 PitchAI. All rights reserved.
"""Define complete dashboard snapshot and service payload models."""

from __future__ import annotations

from typing import TYPE_CHECKING, NotRequired, TypedDict

if TYPE_CHECKING:
    from .account_models import CapacityAccount, HourlyUsageHistory
    from .forecast_models import (
        CapacityBasis,
        CapacityEvent,
        CapacityForecast,
        DashboardWarning,
        ResetBank,
        RunoutForecast,
        WindowAggregate,
    )


class DashboardSource(TypedDict):
    """Represent source freshness and probe status."""

    name: str
    mode: str
    probe_interval_seconds: int
    analytics_probe_interval_seconds: int
    last_safe_probe_at: str | None
    last_analytics_probe_at: str | None
    oldest_account_probe_at: str | None
    newest_account_probe_at: str | None
    stale: bool
    stale_account_count: int
    analytics_stale_account_count: int
    history_error: str | None
    error: str | None


class StatusCounts(TypedDict):
    """Count accounts by normalized availability status."""

    available: int
    five_hour_limited: int
    weekly_limited: int
    auth_invalid: int
    disabled: int
    unknown: int


class WindowAggregates(TypedDict):
    """Group five-hour and weekly aggregate measurements."""

    five_hour: WindowAggregate
    weekly: WindowAggregate


class DashboardSummary(TypedDict):
    """Represent the dashboard's primary aggregate counters."""

    configured_accounts: int
    enabled_accounts: int
    usable_now: int
    status_counts: StatusCounts
    window_aggregates: WindowAggregates
    capacity_basis: CapacityBasis
    next_useful_capacity_at: str | None
    next_useful_capacity_label: str | None
    capacity_event_horizon_seconds: int


class DashboardMethodology(TypedDict):
    """Describe capacity and history interpretation rules."""

    unit: str
    definition: str
    weekly_handling: str
    missing_windows: str
    maximum_not_prediction: bool
    token_history: str
    runout_forecast: str
    reset_bank: str


class DashboardSnapshot(TypedDict):
    """Represent one coherent capacity dashboard response."""

    schema_version: int
    generated_at: str | None
    source: DashboardSource
    summary: DashboardSummary
    forecasts: list[CapacityForecast]
    runout_forecast: RunoutForecast
    usage_history: HourlyUsageHistory
    reset_bank: ResetBank
    warnings: list[DashboardWarning]
    events: list[CapacityEvent]
    accounts: list[CapacityAccount]
    methodology: DashboardMethodology


class HealthPayload(TypedDict):
    """Represent the service health response."""

    status: str
    generated_at: str | None
    source_stale: bool


class ManualProbePayload(TypedDict):
    """Represent a manual refresh response."""

    probe_started: bool
    reason: str
    snapshot: DashboardSnapshot
    retry_after_seconds: NotRequired[int]
