# Copyright (c) 2026 PitchAI. All rights reserved.
"""Per-account analytics: daily token history and the banked reset inventory."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from operator import itemgetter
from typing import TYPE_CHECKING

from .capacity_values import bounded_integer, isoformat, parse_day, parse_timestamp
from .timeseries_types import optional_object, text_value

if TYPE_CHECKING:
    from datetime import datetime

    from .timeseries_types import JsonObject, JsonValue

_TOKEN_SUMMARY_FIELDS = (
    "lifetime_tokens",
    "peak_daily_tokens",
    "longest_running_turn_sec",
    "current_streak_days",
    "longest_streak_days",
)
_TOKEN_HISTORY_DAYS = 7
_RESET_TITLE_LIMIT = 120


@dataclass(frozen=True)
class AnalyticsFreshness:
    """Freshness policy and probe errors for one account's analytics state."""

    now: datetime
    stale_after_seconds: int
    probe_error: str | None
    errors: JsonObject

    def is_stale(self, updated_at: datetime | None) -> bool:
        """Return whether an analytics refresh is missing or older than the policy allows."""
        return updated_at is None or (self.now - updated_at).total_seconds() > self.stale_after_seconds

    def error_for(self, field: str) -> str | None:
        """Return the probe-wide error, else the broker's recorded error for one field."""
        return self.probe_error or text_value(self.errors.get(field))


def token_usage(analytics: JsonObject, freshness: AnalyticsFreshness) -> JsonObject:
    """Normalize the provider's daily token buckets for the trailing week.

    Returns:
        Daily token totals, lifetime summary counters, and their freshness.
    """
    value = analytics.get("token_usage")
    payload = optional_object(value)
    summary_payload = optional_object(payload.get("summary"))
    summary: JsonObject = {key: bounded_integer(summary_payload.get(key), minimum=0) for key in _TOKEN_SUMMARY_FIELDS}
    today = freshness.now.date()
    first_day = today - timedelta(days=_TOKEN_HISTORY_DAYS)
    buckets: list[tuple[str, int]] = []
    raw_buckets = payload.get("daily_usage_buckets")
    if isinstance(raw_buckets, list):
        for raw in raw_buckets:
            if not isinstance(raw, dict):
                continue
            bucket_date = parse_day(raw.get("start_date"))
            tokens = bounded_integer(raw.get("tokens"), minimum=0)
            if bucket_date is None or tokens is None or not first_day <= bucket_date <= today:
                continue
            buckets.append((bucket_date.isoformat(), tokens))
    buckets.sort(key=itemgetter(0))
    daily: list[JsonValue] = [{"date": day, "tokens": tokens} for day, tokens in buckets]
    updated_at = parse_timestamp(analytics.get("token_usage_updated_at"))
    return {
        "available": isinstance(value, dict),
        "granularity": "day",
        "daily": daily,
        "summary": summary,
        "updated_at": isoformat(updated_at),
        "stale": freshness.is_stale(updated_at),
        "probe_error": freshness.error_for("token_usage"),
    }


def reset_credits(
    analytics: JsonObject,
    usage: JsonObject,
    freshness: AnalyticsFreshness,
    *,
    last_probe: datetime | None,
    probe_stale: bool,
) -> JsonObject:
    """Read banked resets, preferring the provider inventory over the usage summary.

    The usage-summary fallback shares the freshness of the account's usage probe.

    Returns:
        The reset inventory with its source, freshness, and probe error.
    """
    inventory = analytics.get("reset_credits")
    if isinstance(inventory, dict):
        updated_at = parse_timestamp(analytics.get("reset_credits_updated_at"))
        return {
            **_reset_inventory(inventory),
            "source": "provider_reset_inventory",
            "updated_at": isoformat(updated_at),
            "stale": freshness.is_stale(updated_at),
            "probe_error": freshness.error_for("reset_credits"),
        }
    return {
        **_reset_inventory(usage.get("rate_limit_reset_credits")),
        "source": "usage_summary",
        "updated_at": isoformat(last_probe),
        "stale": probe_stale,
        "probe_error": freshness.error_for("reset_credits"),
    }


def _reset_inventory(value: JsonValue) -> JsonObject:
    payload = optional_object(value)
    count = bounded_integer(payload.get("available_count", payload.get("availableCount")), minimum=0)
    raw_details = payload.get("credits")
    details: list[JsonValue] = []
    dates_available = False
    if isinstance(raw_details, list):
        for raw in raw_details:
            if not isinstance(raw, dict):
                continue
            title = text_value(raw.get("title"))
            detail: JsonObject = {
                "reset_type": text_value(raw.get("reset_type", raw.get("resetType"))),
                "status": text_value(raw.get("status")),
                "granted_at": isoformat(parse_timestamp(raw.get("granted_at", raw.get("grantedAt")))),
                "expires_at": isoformat(parse_timestamp(raw.get("expires_at", raw.get("expiresAt")))),
                "title": None if title is None else title[:_RESET_TITLE_LIMIT],
            }
            dates_available = dates_available or bool(detail["granted_at"] or detail["expires_at"])
            details.append(detail)
    return {
        "available_count": count,
        "details": details,
        "details_available": isinstance(raw_details, list),
        "dates_available": dates_available,
    }
