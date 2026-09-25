# Copyright (c) 2026 PitchAI. All rights reserved.
"""Define normalized account and token-history payload models."""

from __future__ import annotations

from typing import NotRequired, TypedDict


class CapacityWindow(TypedDict):
    """Represent one normalized provider capacity window."""

    reported: bool
    used_percent: float | None
    remaining_percent: float | None
    reset_at: str | None
    reset_in_seconds: int | None
    window_seconds: int | None


class ResetCreditDetail(TypedDict):
    """Represent one redacted banked-reset inventory item."""

    reset_type: str | None
    status: str | None
    granted_at: str | None
    expires_at: str | None
    title: str | None


class ResetCreditState(TypedDict):
    """Represent one account's normalized banked-reset state."""

    available_count: int | None
    details: list[ResetCreditDetail]
    details_available: bool
    dates_available: bool
    source: str
    updated_at: str | None
    stale: bool
    probe_error: str | None


class TokenDailyUsage(TypedDict):
    """Represent one provider daily token total."""

    date: str
    tokens: int


class TokenUsageSummary(TypedDict):
    """Represent the provider token summary counters."""

    lifetime_tokens: int | None
    peak_daily_tokens: int | None
    longest_running_turn_sec: int | None
    current_streak_days: int | None
    longest_streak_days: int | None


class TokenUsageState(TypedDict):
    """Represent normalized token analytics for one account."""

    available: bool
    granularity: str
    daily: list[TokenDailyUsage]
    summary: TokenUsageSummary
    updated_at: str | None
    stale: bool
    probe_error: str | None


class CapacityAccount(TypedDict):
    """Represent one fully normalized broker account."""

    label: str
    email: str
    enabled: bool
    routing_preferred: bool
    plan_type: str | None
    status: str
    status_reason: str
    availability: str
    auth_valid: bool | None
    selectable_now: bool
    selection_blocked: bool
    safety_floor_active: bool
    five_hour: CapacityWindow
    weekly: CapacityWindow
    token_usage: TokenUsageState
    reset_credits: ResetCreditState
    active_session_count: int
    latest_session_expires_at: str | None
    last_probe_at: str | None
    stale: bool
    stale_seconds: int | None
    probe_error: str | None


class UsageSampleAccount(TypedDict, total=False):
    """Represent the bounded account fields persisted in usage history."""

    enabled: bool
    auth_valid: bool
    status: str | None
    five_used_percent: float | None
    five_reset_at: str | None
    weekly_used_percent: float | None
    weekly_reset_at: str | None
    token_date: str
    tokens_today: int


class UsageSample(TypedDict):
    """Represent one timestamped set of bounded account samples."""

    at: str
    accounts: dict[str, UsageSampleAccount]


class SampleWindow(TypedDict):
    """Represent one comparable capacity window from a stored sample."""

    used_percent: float
    reset_at: str


class HistoryPoint(TypedDict):
    """Represent one hourly token-history point."""

    at: str
    tokens: int
    observed_tokens: int
    reconstructed_tokens: int
    provenance: str
    smoothed_tokens: int
    accounts_reporting: NotRequired[int]


class HistorySeries(TypedDict):
    """Represent hourly token history for one account."""

    label: str
    points: list[HistoryPoint]
    updated_at: str | None
    stale: bool
    native_hour_count: int


class HistorySummary(TypedDict):
    """Represent aggregate token-history counters."""

    seven_day_tokens: int
    average_hourly_tokens: int
    peak_hourly_tokens: int
    trailing_two_hour_tokens: int
    observed_share_percent: float


class HistoryReconstruction(TypedDict):
    """Describe the provenance of reconstructed hourly history."""

    method: str
    daily_totals_preserved: bool
    native_samples_used: bool
    native_hour_count: int
    estimated_hour_count: int
    note: str


class HourlyUsageHistory(TypedDict):
    """Represent the complete seven-day hourly token history."""

    granularity: str
    provider_granularity: str
    timezone: str
    period_start: str
    period_end: str
    point_count: int
    current_hour_partial: bool
    accounts_reporting: int
    configured_accounts: int
    stale_account_count: int
    updated_at: str | None
    combined: list[HistoryPoint]
    series: list[HistorySeries]
    summary: HistorySummary
    reconstruction: HistoryReconstruction


class CapacityBurnRate(TypedDict):
    """Represent a normalized capacity burn-rate estimate."""

    capacity_points_per_hour: float | None
    source: str
    window_key: NotRequired[str]
    lookback_hours: int | None
    fallback_window: NotRequired[str | None]
    confidence: str
    sample_count: NotRequired[int]
    covered_accounts: int
    coefficient_of_variation: float | None
    native_interval_rates: NotRequired[list[float]]
