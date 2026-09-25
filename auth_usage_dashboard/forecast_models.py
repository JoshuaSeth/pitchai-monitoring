# Copyright (c) 2026 PitchAI. All rights reserved.
"""Define capacity-forecast and reset-bank payload models."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, NotRequired, TypedDict

if TYPE_CHECKING:
    from datetime import datetime

    from .account_models import CapacityBurnRate


class ForecastDefinition(NamedTuple):
    """Declare one deterministic forecast horizon and capacity basis."""

    key: str
    label: str
    horizon_seconds: int
    window_key: str | None
    now: datetime


class AccountContribution(NamedTuple):
    """Represent one account's effect on aggregate forecast counters."""

    capacity_points: float
    maximum_points: float
    reset_events: int
    contributes: bool
    weekly_blocked: int
    unknown_windows: int
    measured_windows: int


class ForecastTotals(NamedTuple):
    """Accumulate normalized forecast counters."""

    capacity_points: float
    maximum_points: float
    reset_events: int
    contributors: set[str]
    weekly_blocked: int
    unknown_windows: int
    measured_windows: int


class CapacityBasis(TypedDict):
    """Declare which provider window backs capacity calculations."""

    key: str | None
    label: str | None
    reporting_accounts: int
    eligible_accounts: int
    measurement_status: str


class ResetBankDetail(TypedDict):
    """Represent one reset-bank detail with its account and expiry delta."""

    account_label: str
    reset_type: str | None
    status: str | None
    title: str | None
    granted_at: str | None
    expires_at: str | None
    expires_in_seconds: int | None


class ResetBank(TypedDict):
    """Represent aggregate reset-credit inventory."""

    total_available: int
    accounts_with_known_count: int
    accounts_with_unknown_count: int
    count_only_accounts: int
    detail_count: int
    details: list[ResetBankDetail]
    earliest_expiry_at: str | None
    stale_account_count: int


class WindowAggregate(TypedDict):
    """Represent aggregate remaining capacity for one window class."""

    measurement_status: str
    reporting_accounts: int
    unknown_accounts: int
    remaining_points: float | None
    maximum_known_points: float | None
    remaining_percent: float | None


class CapacityForecast(TypedDict):
    """Represent deterministic capacity available within one horizon."""

    key: str
    label: str
    horizon_seconds: int
    basis_key: str | None
    basis_label: str | None
    capacity_points: float | None
    account_equivalents: float | None
    maximum_points: float | None
    capacity_percent: float | None
    measurement_status: str
    measured_window_accounts: int
    unknown_window_accounts: int
    usable_accounts_now: int
    contributing_accounts: int
    automatic_resets: int
    five_hour_resets: int
    weekly_blocked_accounts: int
    confidence: str


class MeasuredForecast(TypedDict):
    """Hold nullable presentation values derived from measured counters."""

    capacity_points: float | None
    account_equivalents: float | None
    maximum_points: float | None
    capacity_percent: float | None
    measurement_status: str


class CapacityEvent(TypedDict):
    """Represent an upcoming provider-window reset."""

    kind: str
    account_label: str
    at: str
    in_seconds: int
    capacity_points: int
    restores_selectability: bool


class DashboardWarning(TypedDict):
    """Represent one operator-facing dashboard warning."""

    severity: str
    code: str
    message: str
    account_label: NotRequired[str]


class RunoutHorizon(TypedDict):
    """Represent modeled exhaustion risk within one time horizon."""

    key: str
    label: str
    horizon_seconds: int
    probability_percent: int | None
    risk: str
    expected_runout_at: str | None
    likely_window_start: str | None
    likely_window_end: str | None
    initial_capacity_points: float | None
    scheduled_resets: int
    scheduled_five_hour_resets: int
    scheduled_capacity_points: float | None
    scenario_count: int


class BankedResetPolicy(TypedDict):
    """Describe why banked resets are excluded from automatic capacity."""

    available_count: int
    included_as_automatic_capacity: bool
    reason: str


class RunoutMethodology(TypedDict):
    """Describe the runout model and its limitations."""

    model: str
    scenario_count: int
    automatic_resets_included: list[str]
    weekly_handling: str
    limitations: str


class RunoutForecast(TypedDict):
    """Represent probabilistic capacity-exhaustion output."""

    data_available: bool
    generated_at: str | None
    capacity_basis: CapacityBasis
    burn_rate: CapacityBurnRate
    initial_capacity_points: float | None
    usable_accounts_now: int
    horizons: list[RunoutHorizon]
    highest_risk: str
    highest_probability_percent: int | None
    drivers: list[str]
    banked_reset_policy: BankedResetPolicy
    methodology: RunoutMethodology


class CapacityScheduleEvent(TypedDict):
    """Represent an internal capacity addition on the forecast timeline."""

    at: datetime
    account_label: str
    capacity_points: float
