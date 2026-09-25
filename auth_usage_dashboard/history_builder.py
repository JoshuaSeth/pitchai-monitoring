# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build the dashboard's seven-day hourly token history."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, NamedTuple

from .history_points import (
    add_smoothed_values,
    floor_hour,
    hourly_points,
    observed_token_deltas,
    provenance,
)
from .value_parsing import UTC, isoformat, parse_datetime

if TYPE_CHECKING:
    from datetime import datetime

    from .models import (
        CapacityAccount,
        HistoryPoint,
        HistoryReconstruction,
        HistorySeries,
        HistorySummary,
        HourlyUsageHistory,
        UsageSample,
    )

HISTORY_HOURS = 7 * 24


class HistoryInputs(NamedTuple):
    """Bundle the normalized inputs used to assemble a history payload."""

    accounts: list[CapacityAccount]
    reporting: list[CapacityAccount]
    series: list[HistorySeries]
    combined: list[HistoryPoint]
    start: datetime
    now: datetime


def build_hourly_usage_history(
    accounts: list[CapacityAccount],
    *,
    samples: list[UsageSample],
    now: datetime,
) -> HourlyUsageHistory:
    """Build a daily-total-preserving seven-day hourly history.

    Returns:
        The resulting value.

    """
    now = now.astimezone(UTC)
    end = floor_hour(now)
    start = end - timedelta(hours=HISTORY_HOURS - 1)
    hours = _hour_grid(start)
    reporting = _reporting_accounts(accounts)
    observed = observed_token_deltas(samples, start=start, end=now)
    series = _build_series(reporting, hours=hours, observed=observed, now=now)
    combined = _combined_points(series, hours=hours, reporting_count=len(reporting))
    for item in series:
        add_smoothed_values(item["points"])
    return _history_payload(
        HistoryInputs(accounts, reporting, series, combined, start, now),
    )


def _hour_grid(start: datetime) -> list[datetime]:
    hour_offsets = range(HISTORY_HOURS)
    hours = (start + timedelta(hours=offset) for offset in hour_offsets)
    return list(hours)


def _reporting_accounts(
    accounts: list[CapacityAccount],
) -> list[CapacityAccount]:
    reporting: list[CapacityAccount] = [account for account in accounts if account["token_usage"]["available"]]
    return reporting


def _build_series(
    accounts: list[CapacityAccount],
    *,
    hours: list[datetime],
    observed: dict[str, dict[datetime, int]],
    now: datetime,
) -> list[HistorySeries]:
    series: list[HistorySeries] = []
    for account in accounts:
        daily_totals: dict[str, int] = {}
        for point in account["token_usage"]["daily"]:
            daily_totals[point["date"]] = int(point["tokens"])
        points = hourly_points(
            hours,
            daily_totals=daily_totals,
            observed=observed.get(account["label"], {}),
            now=now,
        )
        series.append(_account_series(account, points))
    series.sort(key=lambda item: item["label"].lower())
    return series


def _account_series(
    account: CapacityAccount,
    points: list[HistoryPoint],
) -> HistorySeries:
    native_hour_count = sum(1 for point in points if point["observed_tokens"] > 0)
    return {
        "label": account["label"],
        "points": points,
        "updated_at": account["token_usage"]["updated_at"],
        "stale": account["token_usage"]["stale"],
        "native_hour_count": native_hour_count,
    }


def _combined_points(
    series: list[HistorySeries],
    *,
    hours: list[datetime],
    reporting_count: int,
) -> list[HistoryPoint]:
    combined: list[HistoryPoint] = []
    for index, at in enumerate(hours):
        raw_tokens = sum(item["points"][index]["tokens"] for item in series)
        observed_tokens = sum(item["points"][index]["observed_tokens"] for item in series)
        combined.append(
            {
                "at": isoformat(at),
                "tokens": raw_tokens,
                "observed_tokens": observed_tokens,
                "reconstructed_tokens": max(0, raw_tokens - observed_tokens),
                "provenance": provenance(raw_tokens, observed_tokens),
                "accounts_reporting": reporting_count,
                "smoothed_tokens": 0,
            },
        )
    add_smoothed_values(combined)
    return combined


def _history_payload(inputs: HistoryInputs) -> HourlyUsageHistory:
    observed_total = sum(point["observed_tokens"] for point in inputs.combined)
    return {
        "granularity": "hour",
        "provider_granularity": "daily",
        "timezone": "UTC",
        "period_start": isoformat(inputs.start),
        "period_end": isoformat(inputs.now),
        "point_count": len(inputs.combined),
        "current_hour_partial": True,
        "accounts_reporting": len(inputs.reporting),
        "configured_accounts": len(inputs.accounts),
        "stale_account_count": sum(1 for account in inputs.reporting if account["token_usage"]["stale"]),
        "updated_at": _oldest_update(inputs.reporting),
        "combined": inputs.combined,
        "series": inputs.series,
        "summary": _history_summary(inputs.combined, observed_total=observed_total),
        "reconstruction": _reconstruction(
            inputs.combined,
            observed_total=observed_total,
        ),
    }


def _oldest_update(accounts: list[CapacityAccount]) -> str | None:
    valid_updates: list[datetime] = []
    for account in accounts:
        updated = parse_datetime(account["token_usage"].get("updated_at"))
        if updated is not None:
            valid_updates.append(updated)
    return isoformat(min(valid_updates)) if valid_updates else None


def _history_summary(
    combined: list[HistoryPoint],
    *,
    observed_total: int,
) -> HistorySummary:
    values = [point["tokens"] for point in combined]
    total = sum(values)
    return {
        "seven_day_tokens": total,
        "average_hourly_tokens": round(total / len(combined)) if combined else 0,
        "peak_hourly_tokens": max(values, default=0),
        "trailing_two_hour_tokens": sum(values[-2:]),
        "observed_share_percent": (round(observed_total / total * 100.0, 1) if total else 0.0),
    }


def _reconstruction(
    combined: list[HistoryPoint],
    *,
    observed_total: int,
) -> HistoryReconstruction:
    return {
        "method": "daily-total-constrained hourly allocation with three-hour smoothing",
        "daily_totals_preserved": True,
        "native_samples_used": observed_total > 0,
        "native_hour_count": sum(1 for point in combined if point["observed_tokens"] > 0),
        "estimated_hour_count": sum(1 for point in combined if point["reconstructed_tokens"] > 0),
        "note": (
            "Provider history is daily. Hourly estimates preserve reported daily "
            "totals and are replaced by observed sample deltas as coverage accumulates."
        ),
    }
