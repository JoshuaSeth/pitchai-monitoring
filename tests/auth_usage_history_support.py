# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build strict reusable fixtures for dashboard history and runout tests."""

from __future__ import annotations

from datetime import UTC as DATETIME_UTC
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, TypedDict, Unpack

if TYPE_CHECKING:
    from auth_usage_dashboard.models import (
        CapacityAccount,
        ResetBank,
        TokenDailyUsage,
        UsageSample,
    )

UTC = DATETIME_UTC
NOW = datetime(2026, 7, 11, 12, 30, tzinfo=UTC)


class HistoryAccountOptions(TypedDict, total=False):
    """Describe optional window and provider-history fixture state."""

    remaining: float
    used: float
    weekly_remaining: float
    reset_at: datetime | None
    daily: list[TokenDailyUsage] | None


def account_fixture(
    label: str = "operator@example.com",
    **options: Unpack[HistoryAccountOptions],
) -> CapacityAccount:
    """Build one fully typed capacity account for history tests.

    Returns:
        The resulting value.

    """
    remaining = options.get("remaining", 70)
    used = options.get("used", 30)
    weekly_remaining = options.get("weekly_remaining", 80)
    reset_at = options.get("reset_at") or NOW + timedelta(hours=3)
    daily = options.get("daily") or []
    return {
        "label": label,
        "email": label,
        "enabled": True,
        "routing_preferred": False,
        "plan_type": "pro",
        "auth_valid": True,
        "status": "available",
        "status_reason": "Selectable now",
        "availability": "available",
        "selectable_now": True,
        "selection_blocked": False,
        "safety_floor_active": False,
        "stale": False,
        "five_hour": {
            "reported": True,
            "used_percent": used,
            "remaining_percent": remaining,
            "reset_at": reset_at.isoformat(),
            "reset_in_seconds": 10_800,
            "window_seconds": 18_000,
        },
        "weekly": {
            "reported": True,
            "used_percent": 100 - weekly_remaining,
            "remaining_percent": weekly_remaining,
            "reset_at": (NOW + timedelta(days=5)).isoformat(),
            "reset_in_seconds": 432_000,
            "window_seconds": 604_800,
        },
        "token_usage": {
            "available": True,
            "granularity": "day",
            "daily": daily,
            "summary": {
                "lifetime_tokens": None,
                "peak_daily_tokens": None,
                "longest_running_turn_sec": None,
                "current_streak_days": None,
                "longest_streak_days": None,
            },
            "updated_at": NOW.isoformat(),
            "stale": False,
            "probe_error": None,
        },
        "reset_credits": {
            "available_count": 0,
            "details": [],
            "details_available": True,
            "dates_available": False,
            "source": "provider_reset_inventory",
            "updated_at": NOW.isoformat(),
            "stale": False,
            "probe_error": None,
        },
        "active_session_count": 0,
        "latest_session_expires_at": None,
        "last_probe_at": NOW.isoformat(),
        "stale_seconds": 0,
        "probe_error": None,
    }


def sample_fixture(at: datetime, used: float, tokens: int = 0) -> UsageSample:
    """Build one native broker usage sample.

    Returns:
        The resulting value.

    """
    return {
        "at": at.isoformat().replace("+00:00", "Z"),
        "accounts": {
            "operator@example.com": {
                "enabled": True,
                "auth_valid": True,
                "status": "available",
                "five_used_percent": used,
                "five_reset_at": (NOW + timedelta(hours=3)).isoformat(),
                "weekly_used_percent": 20,
                "weekly_reset_at": (NOW + timedelta(days=5)).isoformat(),
                "token_date": at.date().isoformat(),
                "tokens_today": tokens,
            },
        },
    }


def reset_bank_fixture(total: int) -> ResetBank:
    """Build a complete reset-bank fixture with one aggregate count.

    Returns:
        The resulting value.

    """
    return {
        "total_available": total,
        "accounts_with_known_count": 1,
        "accounts_with_unknown_count": 0,
        "count_only_accounts": 1 if total else 0,
        "detail_count": 0,
        "details": [],
        "earliest_expiry_at": None,
        "stale_account_count": 0,
    }
