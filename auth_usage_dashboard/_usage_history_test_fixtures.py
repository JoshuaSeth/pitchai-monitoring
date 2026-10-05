# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed parsed-account and sample fixtures for the legacy history and run-out tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue

NOW = datetime(2026, 7, 11, 12, 30, tzinfo=UTC)
OPERATOR = "operator@example.com"
FIVE_HOUR_SECONDS = 18_000
WEEK_SECONDS = 604_800
WEEKLY_REMAINING_PERCENT = 80


def dashboard_account(
    *,
    remaining: float = 70,
    reset_at: datetime | None = None,
    daily: list[JsonValue] | None = None,
) -> JsonObject:
    """Return one selectable parsed dashboard account for the operator.

    Returns:
        A parsed account whose five-hour usage is the complement of ``remaining``.
    """
    return {
        "label": OPERATOR,
        "email": OPERATOR,
        "enabled": True,
        "auth_valid": True,
        "status": "available",
        "availability": "available",
        "selectable_now": True,
        "stale": False,
        "five_hour": {
            "reported": True,
            "used_percent": 100 - remaining,
            "remaining_percent": remaining,
            "reset_at": (reset_at or NOW + timedelta(hours=3)).isoformat(),
            "window_seconds": FIVE_HOUR_SECONDS,
        },
        "weekly": {
            "reported": True,
            "used_percent": 100 - WEEKLY_REMAINING_PERCENT,
            "remaining_percent": WEEKLY_REMAINING_PERCENT,
            "reset_at": (NOW + timedelta(days=5)).isoformat(),
            "window_seconds": WEEK_SECONDS,
        },
        "token_usage": {
            "available": True,
            "daily": daily or [],
            "updated_at": NOW.isoformat(),
            "stale": False,
        },
        "reset_credits": {"available_count": 0, "details": [], "stale": False},
    }


def usage_sample(at: datetime, used: float, tokens: int = 0) -> JsonObject:
    """Return one persisted broker sample for the operator at ``at``.

    Returns:
        A version-one sample carrying five-hour usage and today's token count.
    """
    return {
        "at": at.isoformat().replace("+00:00", "Z"),
        "accounts": {
            OPERATOR: {
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


def trailing_samples(*used: float) -> list[JsonObject]:
    """Return hourly samples ending now, one per five-hour usage value.

    Returns:
        Samples spaced one hour apart, oldest first, without token counts.
    """
    newest_offset = len(used) - 1
    return [usage_sample(NOW - timedelta(hours=newest_offset - index), value) for index, value in enumerate(used)]
