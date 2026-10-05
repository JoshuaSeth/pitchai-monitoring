# Copyright (c) 2026 PitchAI. All rights reserved.
"""Eight-account broker fleet rendered by the legacy dashboard UI test."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, NamedTuple

from ._broker_account_test_fixtures import add_usage_credits, analytics_state, keep_only_weekly_window, raw_account

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue

ONBOARDING = "onboarding.bigi.net"
RELAY = "svxjvmk78b@privaterelay.appleid.com"
DAILY_TOKEN_STEP = 12_000
TOKENS_PER_OFFSET_MINUTE = 40
HISTORY_DAYS = 7


class UiAccountSpec(NamedTuple):
    """Provider state for one weekly-only fleet account."""

    label: str
    availability: str
    five_used: float
    weekly_used: float
    offset_minutes: int


UI_ACCOUNTS = (
    UiAccountSpec("elise@pitchai.net", "available", 38, 31, 252),
    UiAccountSpec("info@pitchai.net", "auth_invalid", 100, 45, 55),
    UiAccountSpec("jozuasethvanderbijl@gmail.com", "available", 17, 20, 214),
    UiAccountSpec(ONBOARDING, "available", 22, 32, 161),
    UiAccountSpec("sales@pitchai.net", "auth_invalid", 100, 19, 34),
    UiAccountSpec("seth.vanderbijl@pitchai.net", "available", 10, 25, 90),
    UiAccountSpec("support@pitchai.net", "rate_limited", 4, 100, 298),
    UiAccountSpec(RELAY, "available", 74, 12, 207),
)


def ui_account(spec: UiAccountSpec, now: datetime) -> JsonObject:
    """Return one weekly-only account with a week of usage, credits, and banked resets.

    Returns:
        A raw broker account as the dashboard source would read it at ``now``.
    """
    banked = spec.offset_minutes % 4
    days = range(HISTORY_DAYS)
    token_counts = [(day + 1) * DAILY_TOKEN_STEP + spec.offset_minutes * TOKENS_PER_OFFSET_MINUTE for day in days]
    dates = [(now.date() - timedelta(days=HISTORY_DAYS - 1 - day)).isoformat() for day in days]
    dated_counts = zip(dates, token_counts, strict=True)
    buckets: list[JsonValue] = [{"start_date": date, "tokens": tokens} for date, tokens in dated_counts]
    reset_details: list[JsonValue] = []
    if banked:
        reset_details.append({
            "reset_type": "weekly",
            "status": "available",
            "granted_at": (now - timedelta(days=2)).isoformat(),
            "expires_at": (now + timedelta(days=8, hours=spec.offset_minutes % 5)).isoformat(),
            "title": "Weekly usage reset",
        })
    analytics = analytics_state(
        now - timedelta(seconds=35),
        lifetime_tokens=sum(token_counts),
        buckets=buckets,
        reset_credits=reset_details,
        available_count=banked,
    )
    raw = raw_account(
        spec.label,
        now=now,
        account_id=f"internal-{spec.offset_minutes}",
        availability=spec.availability,
        routing_preferred=spec.label == RELAY,
        five_used=spec.five_used,
        five_reset=now + timedelta(minutes=spec.offset_minutes),
        weekly_used=spec.weekly_used,
        weekly_reset=now + timedelta(days=5, hours=spec.offset_minutes % 8),
        last_probe=now - timedelta(seconds=22),
        credits={"available_count": banked},
        analytics=analytics,
    )
    keep_only_weekly_window(raw)
    add_usage_credits(raw, balance="62500", overage_reached=False, spending_reached=False)
    return raw


def ui_accounts() -> list[JsonObject]:
    """Return the eight-account fleet relative to the current moment.

    Returns:
        Raw broker accounts in label order.
    """
    now = datetime.now(UTC)
    return [ui_account(spec, now) for spec in UI_ACCOUNTS]
