# Copyright (c) 2026 PitchAI. All rights reserved.
"""Reset-aware aggregate capacity burn windows for scheduler consumers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from .history import isoformat, parse_datetime
from .scheduling_capacity_burn_deltas import eligible_account
from .scheduling_capacity_burn_samples import BurnWindowTotals, measure_burn_samples
from .scheduling_capacity_timeline_values import aware_datetime
from .timeseries_types import (
    nonnegative_integer,
    number_value,
    optional_object,
    text_value,
)

if TYPE_CHECKING:
    from .timeseries_types import JsonObject

type BurnWindowPeriod = tuple[datetime, datetime, int]


def build_capacity_burn_windows(
    accounts: list[JsonObject],
    *,
    samples: list[JsonObject],
    generated_at: str | None,
    window_key: str,
) -> JsonObject:
    """Build the required one-hour and 24-hour scheduler burn windows."""
    observed_at = aware_datetime(generated_at)
    if observed_at is None:
        message = "operator scheduling snapshot has an invalid generated timestamp"
        raise ValueError(message)
    return {
        "last_hour": capacity_burn_window(
            accounts,
            samples=samples,
            now=observed_at,
            window_hours=1,
            window_key=window_key,
        ),
        "last_24_hours": capacity_burn_window(
            accounts,
            samples=samples,
            now=observed_at,
            window_hours=24,
            window_key=window_key,
        ),
    }


def capacity_burn_window(
    accounts: list[JsonObject],
    *,
    samples: list[JsonObject],
    now: datetime,
    window_hours: int,
    window_key: str = "five_hour",
) -> JsonObject:
    """Measure reset-aware capacity and provider-token burn over one window.

    Native broker samples are clipped at the requested boundary. Intervals that
    cross a provider reset, regress, or contain a long sampling gap are excluded.
    """
    ends_at = now.astimezone(UTC)
    starts_at = ends_at - timedelta(hours=window_hours)
    period = starts_at, ends_at, window_hours
    totals = measure_burn_samples(
        accounts,
        samples,
        starts_at=starts_at,
        ends_at=ends_at,
        window_key=window_key,
    )
    if totals.covered_seconds > 0:
        return _native_payload(totals, period=period)
    return _estimated_payload(accounts, period=period, window_key=window_key)


def _native_payload(
    totals: BurnWindowTotals,
    *,
    period: BurnWindowPeriod,
) -> JsonObject:
    _starts_at, _ends_at, window_hours = period
    measured_hours = totals.covered_seconds / 3600.0
    coverage = min(100.0, measured_hours / window_hours * 100.0)
    details: JsonObject = {
        "source": "native_broker_samples",
        "confidence": _confidence(coverage, len(totals.capacity_labels)),
        "sample_count": len(totals.sample_times),
        "covered_accounts": len(totals.capacity_labels),
        "coverage_percent": round(coverage, 1),
        "measured_hours": round(measured_hours, 3),
        "provider_tokens": round(totals.provider_tokens),
        "token_covered_accounts": len(totals.token_labels),
    }
    return _payload(
        period,
        points=totals.capacity_points,
        rate=totals.capacity_points / measured_hours,
        details=details,
    )


def _estimated_payload(
    accounts: list[JsonObject],
    *,
    period: BurnWindowPeriod,
    window_key: str,
) -> JsonObject:
    _starts_at, ends_at, window_hours = period
    rates = _current_window_rates(accounts, now=ends_at, window_key=window_key)
    rate = sum(rates)
    details: JsonObject = {
        "source": "current_window_average",
        "confidence": "medium" if len(rates) >= 2 else "low",
        "sample_count": 0,
        "covered_accounts": 0,
        "coverage_percent": 0.0,
        "measured_hours": 0.0,
        "provider_tokens": None,
        "token_covered_accounts": 0,
    }
    return _payload(period, points=rate * window_hours, rate=rate, details=details)


def _current_window_rates(
    accounts: list[JsonObject],
    *,
    now: datetime,
    window_key: str,
) -> list[float]:
    rates: list[float] = []
    for account in accounts:
        window = optional_object(account.get(window_key))
        if not eligible_account(account) or window.get("reported") is not True:
            continue
        used = number_value(window.get("used_percent"))
        reset_at = parse_datetime(text_value(window.get("reset_at")))
        window_seconds = nonnegative_integer(window.get("window_seconds")) or 18_000
        if used is None or reset_at is None:
            continue
        elapsed_hours = (
            now - (reset_at - timedelta(seconds=window_seconds))
        ).total_seconds() / 3600.0
        if 1 / 12 <= elapsed_hours <= window_seconds / 3600.0 + 0.25:
            rates.append(max(0.0, used / elapsed_hours))
    return rates


def _confidence(coverage: float, covered_accounts: int) -> str:
    if coverage >= 80.0 and covered_accounts >= 2:
        return "high"
    if coverage >= 20.0 or covered_accounts >= 2:
        return "medium"
    return "low"


def _payload(
    period: BurnWindowPeriod,
    *,
    points: float,
    rate: float,
    details: JsonObject,
) -> JsonObject:
    starts_at, ends_at, window_hours = period
    return {
        "window_hours": window_hours,
        "starts_at": isoformat(starts_at),
        "ends_at": isoformat(ends_at),
        "capacity_points": round(max(0.0, points), 2),
        "capacity_points_per_hour": round(max(0.0, rate), 2),
        **details,
    }
