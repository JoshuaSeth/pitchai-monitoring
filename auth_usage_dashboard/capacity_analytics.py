# Copyright (c) 2026 PitchAI. All rights reserved.
"""Normalize provider token analytics and banked reset inventory."""

from __future__ import annotations

from datetime import timedelta
from operator import itemgetter
from typing import TYPE_CHECKING

from .value_parsing import (
    integer,
    limited_string,
    object_value,
    optional_isoformat,
    parse_date,
    parse_datetime,
    string,
)

if TYPE_CHECKING:
    from datetime import datetime

    from .json_contract import JsonObject, JsonValue
    from .models import (
        ResetCreditDetail,
        ResetCreditState,
        TokenDailyUsage,
        TokenUsageState,
        TokenUsageSummary,
    )


def parse_reset_credits(value: JsonValue) -> ResetCreditState:
    """Normalize only the bounded reset-credit fields safe for the dashboard.

    Returns:
        The resulting value.

    """
    payload = value if isinstance(value, dict) else {}
    count = integer(
        payload.get("available_count", payload.get("availableCount")),
        minimum=0,
    )
    raw_details = payload.get("credits")
    details: list[ResetCreditDetail] = []
    if isinstance(raw_details, list):
        details.extend(_reset_credit_detail(raw) for raw in raw_details if isinstance(raw, dict))
    return {
        "available_count": count,
        "details": details,
        "details_available": isinstance(raw_details, list),
        "dates_available": any(detail["granted_at"] or detail["expires_at"] for detail in details),
        "source": "unavailable",
        "updated_at": None,
        "stale": True,
        "probe_error": None,
    }


def _reset_credit_detail(raw: JsonObject) -> ResetCreditDetail:
    return {
        "reset_type": string(raw.get("reset_type", raw.get("resetType"))),
        "status": string(raw.get("status")),
        "granted_at": optional_isoformat(
            parse_datetime(raw.get("granted_at", raw.get("grantedAt"))),
        ),
        "expires_at": optional_isoformat(
            parse_datetime(raw.get("expires_at", raw.get("expiresAt"))),
        ),
        "title": limited_string(raw.get("title"), 120),
    }


def parse_token_usage(
    value: JsonValue,
    *,
    updated_at: JsonValue,
    now: datetime,
    stale_after_seconds: int,
    probe_error: str | None,
) -> TokenUsageState:
    """Normalize the provider's seven-day daily token analytics.

    Returns:
        The resulting value.

    """
    payload = value if isinstance(value, dict) else {}
    summary = _token_summary(object_value(payload, "summary"))
    daily = _daily_usage(payload, now=now)
    parsed_updated_at = parse_datetime(updated_at)
    stale = parsed_updated_at is None or (now - parsed_updated_at).total_seconds() > stale_after_seconds
    return {
        "available": isinstance(value, dict),
        "granularity": "day",
        "daily": daily,
        "summary": summary,
        "updated_at": optional_isoformat(parsed_updated_at),
        "stale": stale,
        "probe_error": probe_error,
    }


def _token_summary(payload: JsonObject) -> TokenUsageSummary:
    return {
        "lifetime_tokens": integer(payload.get("lifetime_tokens"), minimum=0),
        "peak_daily_tokens": integer(payload.get("peak_daily_tokens"), minimum=0),
        "longest_running_turn_sec": integer(
            payload.get("longest_running_turn_sec"),
            minimum=0,
        ),
        "current_streak_days": integer(
            payload.get("current_streak_days"),
            minimum=0,
        ),
        "longest_streak_days": integer(
            payload.get("longest_streak_days"),
            minimum=0,
        ),
    }


def _daily_usage(payload: JsonObject, *, now: datetime) -> list[TokenDailyUsage]:
    first_day = now.date() - timedelta(days=7)
    daily: list[TokenDailyUsage] = []
    raw_buckets = payload.get("daily_usage_buckets")
    if not isinstance(raw_buckets, list):
        return daily
    for raw in raw_buckets:
        if not isinstance(raw, dict):
            continue
        bucket_date = parse_date(raw.get("start_date"))
        tokens = integer(raw.get("tokens"), minimum=0)
        if bucket_date is None or tokens is None:
            continue
        if first_day <= bucket_date <= now.date():
            daily.append({"date": bucket_date.isoformat(), "tokens": tokens})
    daily.sort(key=itemgetter("date"))
    return daily
