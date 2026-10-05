# Copyright (c) 2026 PitchAI. All rights reserved.
"""Seven-day hourly token history and the public usage-history interface."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import TYPE_CHECKING

from .history_allocation import hour_points, hourly_allocations
from .history_burn import capacity_burn_rate
from .history_observed import observed_token_deltas
from .history_store import SAMPLE_SCHEMA_VERSION, UsageSampleStore
from .history_values import floor_hour, isoformat, iterated_items, parse_datetime, whole_number

if TYPE_CHECKING:
    from datetime import datetime

    from .history_allocation import HourTokens
    from .timeseries_types import JsonObject, JsonValue

__all__ = [
    "HISTORY_HOURS",
    "SAMPLE_SCHEMA_VERSION",
    "UTC",
    "UsageSampleStore",
    "build_hourly_usage_history",
    "capacity_burn_rate",
    "floor_hour",
    "isoformat",
    "parse_datetime",
]

HISTORY_HOURS = 7 * 24
_RECONSTRUCTION_METHOD = "daily-total-constrained hourly allocation with three-hour smoothing"
_RECONSTRUCTION_NOTE = (
    "Provider history is daily. Hourly estimates preserve reported daily totals and are replaced by "
    "observed sample deltas as coverage accumulates."
)


@dataclass(frozen=True)
class _AccountSeries:
    label: str
    allocations: list[HourTokens]
    updated_at: JsonValue
    stale: JsonValue


def build_hourly_usage_history(
    accounts: list[JsonObject],
    *,
    samples: list[JsonObject],
    now: datetime,
) -> JsonObject:
    """Reconstruct seven days of hourly token usage per account and combined.

    Returns:
        Combined and per-account hourly points with summary and provenance.
    """
    current = now.astimezone(UTC)
    start = floor_hour(current) - timedelta(hours=HISTORY_HOURS - 1)
    offsets = range(HISTORY_HOURS)
    hours = [start + timedelta(hours=offset) for offset in offsets]
    reporting = [account for account in accounts if _token_usage(account)["available"]]
    observed = observed_token_deltas(samples, start=start, end=current)
    series = _account_series(reporting, hours=hours, observed=observed, now=current)
    combined = _combined_allocations(series, hour_count=len(hours))
    updated_values = [parse_datetime(_token_usage(account).get("updated_at")) for account in reporting]
    valid_updates = [value for value in updated_values if value is not None]
    return {
        "granularity": "hour",
        "provider_granularity": "daily",
        "timezone": "UTC",
        "period_start": isoformat(start),
        "period_end": isoformat(current),
        "point_count": len(combined),
        "current_hour_partial": True,
        "accounts_reporting": len(reporting),
        "configured_accounts": len(accounts),
        "stale_account_count": sum(1 for account in reporting if _token_usage(account)["stale"]),
        "updated_at": isoformat(min(valid_updates)) if valid_updates else None,
        "combined": hour_points(hours, combined, extra={"accounts_reporting": len(reporting)}),
        "series": [_series_payload(item, hours=hours) for item in series],
        "summary": _summary(combined),
        "reconstruction": _reconstruction(combined),
    }


def _token_usage(account: JsonObject) -> JsonObject:
    token_usage = account["token_usage"]
    if isinstance(token_usage, dict):
        return token_usage
    message = "reporting account token usage must be a JSON object"
    raise TypeError(message)


def _account_series(
    reporting: list[JsonObject],
    *,
    hours: list[datetime],
    observed: dict[str, dict[datetime, int]],
    now: datetime,
) -> list[_AccountSeries]:
    series: list[_AccountSeries] = []
    for account in reporting:
        label = account["label"]
        if not isinstance(label, str):
            message = "reporting account label must be text"
            raise TypeError(message)
        token_usage = _token_usage(account)
        allocations = hourly_allocations(
            hours,
            daily_totals=_daily_totals(token_usage["daily"]),
            observed=observed.get(label, {}),
            now=now,
        )
        series.append(_AccountSeries(label, allocations, token_usage["updated_at"], token_usage["stale"]))
    series.sort(key=lambda item: item.label.lower())
    return series


def _daily_totals(daily: JsonValue) -> dict[str, int]:
    totals: dict[str, int] = {}
    for point in iterated_items(daily, description="reporting account daily token usage"):
        if not isinstance(point, dict):
            message = "daily token usage points must be JSON objects"
            raise TypeError(message)
        day = point["date"]
        tokens = whole_number(point["tokens"])
        if isinstance(day, (list, dict)):
            message = "daily token usage dates must be hashable"
            raise TypeError(message)
        if isinstance(day, str):
            totals[day] = tokens
    return totals


def _combined_allocations(series: list[_AccountSeries], *, hour_count: int) -> list[HourTokens]:
    combined: list[HourTokens] = []
    for index in range(hour_count):
        tokens = sum(item.allocations[index][0] for item in series)
        observed_tokens = sum(item.allocations[index][1] for item in series)
        combined.append((tokens, observed_tokens))
    return combined


def _series_payload(item: _AccountSeries, *, hours: list[datetime]) -> JsonObject:
    return {
        "label": item.label,
        "points": hour_points(hours, item.allocations, extra={}),
        "updated_at": item.updated_at,
        "stale": item.stale,
        "native_hour_count": sum(1 for _tokens, observed_tokens in item.allocations if observed_tokens > 0),
    }


def _summary(combined: list[HourTokens]) -> JsonObject:
    values = [tokens for tokens, _observed_tokens in combined]
    observed_total = sum(observed_tokens for _tokens, observed_tokens in combined)
    total = sum(values)
    return {
        "seven_day_tokens": total,
        "average_hourly_tokens": round(total / len(combined)) if combined else 0,
        "peak_hourly_tokens": max(values, default=0),
        "trailing_two_hour_tokens": sum(values[-2:]),
        "observed_share_percent": round(observed_total / total * 100.0, 1) if total else 0.0,
    }


def _reconstruction(combined: list[HourTokens]) -> JsonObject:
    observed_total = sum(observed_tokens for _tokens, observed_tokens in combined)
    return {
        "method": _RECONSTRUCTION_METHOD,
        "daily_totals_preserved": True,
        "native_samples_used": observed_total > 0,
        "native_hour_count": sum(1 for _tokens, observed_tokens in combined if observed_tokens > 0),
        "estimated_hour_count": sum(1 for tokens, observed_tokens in combined if tokens - observed_tokens > 0),
        "note": _RECONSTRUCTION_NOTE,
    }
