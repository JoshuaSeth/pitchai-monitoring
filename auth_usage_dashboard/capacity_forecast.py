# Copyright (c) 2026 PitchAI. All rights reserved.
"""Forecast deterministic capacity within operator-facing horizons."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from .capacity_forecast_support import (
    current_pool,
    forecast_confidence,
    primary_window,
    scheduled_resets,
)
from .capacity_windows import window_label
from .forecast_models import (
    AccountContribution,
    ForecastDefinition,
    ForecastTotals,
)
from .value_parsing import parse_datetime

if TYPE_CHECKING:
    from datetime import datetime

    from .forecast_models import MeasuredForecast
    from .models import CapacityAccount, CapacityForecast, CapacityWindow

FORECAST_HORIZONS = (
    ("hour", "Next hour", 60 * 60),
    ("six_hours", "Next 6 hours", 6 * 60 * 60),
    ("day", "Next 24 hours", 24 * 60 * 60),
)


def build_capacity_forecasts(
    accounts: list[CapacityAccount],
    *,
    now: datetime,
    window_key: str | None,
) -> list[CapacityForecast]:
    """Build every declared deterministic capacity horizon.

    Returns:
        The resulting collection.

    """
    forecasts: list[CapacityForecast] = []
    for key, label, seconds in FORECAST_HORIZONS:
        definition = ForecastDefinition(key, label, seconds, window_key, now)
        forecasts.append(_forecast(accounts, definition))
    return forecasts


def _forecast(
    accounts: list[CapacityAccount],
    definition: ForecastDefinition,
) -> CapacityForecast:
    totals = ForecastTotals(0.0, 0.0, 0, set(), 0, 0, 0)
    for account in accounts:
        contribution = _account_contribution(account, definition)
        totals = _add_contribution(totals, account["label"], contribution)
    measured = _measured_forecast(totals)
    usable_now, stale_enabled = current_pool(accounts)
    return {
        "key": definition.key,
        "label": definition.label,
        "horizon_seconds": definition.horizon_seconds,
        "basis_key": definition.window_key,
        "basis_label": window_label(definition.window_key),
        "capacity_points": measured["capacity_points"],
        "account_equivalents": measured["account_equivalents"],
        "maximum_points": measured["maximum_points"],
        "capacity_percent": measured["capacity_percent"],
        "measurement_status": measured["measurement_status"],
        "measured_window_accounts": totals.measured_windows,
        "unknown_window_accounts": totals.unknown_windows,
        "usable_accounts_now": usable_now,
        "contributing_accounts": len(totals.contributors),
        "automatic_resets": totals.reset_events,
        "five_hour_resets": (totals.reset_events if definition.window_key == "five_hour" else 0),
        "weekly_blocked_accounts": totals.weekly_blocked,
        "confidence": forecast_confidence(
            measured_windows=totals.measured_windows,
            unknown_windows=totals.unknown_windows,
            stale_enabled=stale_enabled,
        ),
    }


def _account_contribution(
    account: CapacityAccount,
    definition: ForecastDefinition,
) -> AccountContribution:
    if not account["enabled"]:
        return AccountContribution(
            0.0,
            0.0,
            0,
            contributes=False,
            weekly_blocked=0,
            unknown_windows=0,
            measured_windows=0,
        )
    primary = primary_window(account, definition.window_key)
    if primary is None:
        return AccountContribution(
            0.0,
            0.0,
            0,
            contributes=False,
            weekly_blocked=0,
            unknown_windows=1,
            measured_windows=0,
        )
    if primary["reported"] is not True:
        weekly_blocked = int(account["status"] == "weekly_limited")
        return AccountContribution(
            0.0,
            0.0,
            0,
            contributes=False,
            weekly_blocked=weekly_blocked,
            unknown_windows=1,
            measured_windows=0,
        )
    return _measured_contribution(account, definition, primary)


def _measured_contribution(
    account: CapacityAccount,
    definition: ForecastDefinition,
    primary: CapacityWindow,
) -> AccountContribution:
    horizon_end = definition.now + timedelta(seconds=definition.horizon_seconds)
    primary_reset = parse_datetime(primary["reset_at"])
    window_seconds = primary["window_seconds"] or 18_000
    resets = scheduled_resets(
        first_reset=primary_reset,
        window_seconds=window_seconds,
        now=definition.now,
        horizon_end=horizon_end,
    )
    unknown_windows = int(primary_reset is None)
    theoretical_resets = definition.horizon_seconds // window_seconds if primary_reset is None else len(resets)
    maximum_points = 100.0 * (1 + theoretical_resets)
    weekly_reset = parse_datetime(account["weekly"]["reset_at"])
    weekly_limited = account["status"] == "weekly_limited"
    weekly_blocked = int(
        weekly_limited and (weekly_reset is None or weekly_reset > horizon_end),
    )
    current_points = _current_capacity(account, primary)
    reset_events = _eligible_reset_count(
        account,
        resets,
        window_key=definition.window_key,
        weekly_reset=weekly_reset,
    )
    return AccountContribution(
        current_points + 100.0 * reset_events,
        maximum_points,
        reset_events,
        current_points > 0 or reset_events > 0,
        weekly_blocked,
        unknown_windows,
        1,
    )


def _current_capacity(account: CapacityAccount, window: CapacityWindow) -> float:
    remaining = window["remaining_percent"]
    if account["selectable_now"] and not account["stale"] and remaining is not None and remaining > 0:
        return float(remaining)
    return 0.0


def _eligible_reset_count(
    account: CapacityAccount,
    resets: list[datetime],
    *,
    window_key: str | None,
    weekly_reset: datetime | None,
) -> int:
    if account["auth_valid"] is not True or account["stale"]:
        return 0
    count = 0
    weekly_limited = account["status"] == "weekly_limited"
    for reset_at in resets:
        blocked = window_key == "five_hour" and weekly_limited and (weekly_reset is None or reset_at < weekly_reset)
        if not blocked:
            count += 1
    return count


def _add_contribution(
    totals: ForecastTotals,
    account_label: str,
    contribution: AccountContribution,
) -> ForecastTotals:
    contributors = set(totals.contributors)
    if contribution.contributes:
        contributors.add(account_label)
    return ForecastTotals(
        totals.capacity_points + contribution.capacity_points,
        totals.maximum_points + contribution.maximum_points,
        totals.reset_events + contribution.reset_events,
        contributors,
        totals.weekly_blocked + contribution.weekly_blocked,
        totals.unknown_windows + contribution.unknown_windows,
        totals.measured_windows + contribution.measured_windows,
    )


def _measured_forecast(totals: ForecastTotals) -> MeasuredForecast:
    if not totals.measured_windows:
        return {
            "capacity_points": None,
            "account_equivalents": None,
            "maximum_points": None,
            "capacity_percent": None,
            "measurement_status": "unavailable",
        }
    capacity_percent = min(
        100.0,
        totals.capacity_points / totals.maximum_points * 100.0,
    )
    return {
        "capacity_points": round(totals.capacity_points, 1),
        "account_equivalents": round(totals.capacity_points / 100.0, 2),
        "maximum_points": round(totals.maximum_points, 1),
        "capacity_percent": round(capacity_percent, 1),
        "measurement_status": "partial" if totals.unknown_windows else "complete",
    }
