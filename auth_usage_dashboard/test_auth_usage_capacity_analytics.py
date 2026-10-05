# Copyright (c) 2026 PitchAI. All rights reserved.
"""Proof for legacy token-usage history and reset-bank analytics in the snapshot."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING

from ._broker_account_test_fixtures import (
    NOW,
    analytics_state,
    integer,
    member,
    objects,
    raw_account,
    snapshot_of,
    text,
)
from ._timeseries_test_fixtures import check, check_equal, require_array

if TYPE_CHECKING:
    from .timeseries_types import JsonObject

CREDIT_ID = "must-not-escape-credit-id"
PROVIDER_COPY = "must-not-escape-provider-copy"


def test_usage_history_combines_authoritative_daily_buckets() -> None:
    """Prove hourly history preserves and combines each account's daily buckets."""
    analytics_a = analytics_state(
        NOW - timedelta(minutes=2),
        lifetime_tokens=20_000,
        buckets=[
            {"start_date": "2026-07-09", "tokens": 1_000},
            {"start_date": "2026-07-10", "tokens": 2_000},
            {"start_date": "2026-07-11", "tokens": 500},
        ],
        reset_credits=[],
        available_count=0,
    )
    analytics_b = analytics_state(
        NOW - timedelta(minutes=3),
        lifetime_tokens=30_000,
        buckets=[
            {"start_date": "2026-07-09", "tokens": 400},
            {"start_date": "2026-07-11", "tokens": 600},
        ],
        reset_credits=[],
        available_count=0,
    )

    snapshot = snapshot_of([
        raw_account("a@example.com", analytics=analytics_a),
        raw_account("b@example.com", analytics=analytics_b),
    ])

    history = member(snapshot, "usage_history")
    check_equal(history["provider_granularity"], "daily", "provider granularity")
    check_equal(history["granularity"], "hour", "history granularity")
    check_equal(history["point_count"], 168, "hourly points")
    check_equal(history["accounts_reporting"], 2, "accounts reporting history")
    by_date: dict[str, int] = {}
    for point in objects(history["combined"], "combined history"):
        day = text(point["at"], "history point time")[:10]
        by_date[day] = by_date.get(day, 0) + integer(point["tokens"], "history point tokens")
    check_equal(by_date["2026-07-09"], 1_400, "July 9 tokens")
    check_equal(by_date["2026-07-10"], 2_000, "July 10 tokens")
    check_equal(by_date["2026-07-11"], 1_100, "July 11 tokens")
    summary = member(history, "summary")
    check_equal(summary["seven_day_tokens"], 4_500, "seven-day tokens")
    check_equal(summary["observed_share_percent"], 0, "observed share")
    check_equal(len(require_array(history["series"], "history series")), 2, "per-account series")


def test_reset_bank_exposes_dates_but_not_provider_ids_or_private_copy() -> None:
    """Prove the reset bank keeps dates while dropping provider ids and copy."""
    credit: JsonObject = {
        "id": CREDIT_ID,
        "reset_type": "weekly",
        "status": "available",
        "granted_at": "2026-07-10T08:00:00Z",
        "expires_at": "2026-07-18T08:00:00Z",
        "title": "Weekly reset",
        "description": PROVIDER_COPY,
    }
    analytics = analytics_state(NOW, buckets=[], reset_credits=[credit], available_count=1)

    snapshot = snapshot_of([raw_account("bank@example.com", analytics=analytics)])

    bank = member(snapshot, "reset_bank")
    check_equal(bank["total_available"], 1, "banked resets")
    check_equal(
        bank["details"],
        [
            {
                "account_label": "bank@example.com",
                "reset_type": "weekly",
                "status": "available",
                "title": "Weekly reset",
                "granted_at": "2026-07-10T08:00:00Z",
                "expires_at": "2026-07-18T08:00:00Z",
                "expires_in_seconds": 590_400,
            },
        ],
        "reset bank details",
    )
    encoded = json.dumps(snapshot)
    check(CREDIT_ID not in encoded, "provider credit id is dropped")
    check(PROVIDER_COPY not in encoded, "provider copy is dropped")
