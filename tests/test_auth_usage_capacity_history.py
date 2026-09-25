# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock dashboard provider history aggregation and reset-bank privacy."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING

from auth_usage_dashboard.capacity import build_dashboard_snapshot
from domain_checks.testing import verify
from tests.auth_usage_capacity_support import NOW, account_fixture

if TYPE_CHECKING:
    from auth_usage_dashboard.json_contract import JsonObject

EXPECTED_HISTORY_POINT_COUNT = 168
EXPECTED_REPORTING_ACCOUNT_COUNT = 2
EXPECTED_JULY_NINTH_TOKENS = 1_400
EXPECTED_JULY_TENTH_TOKENS = 2_000
EXPECTED_JULY_ELEVENTH_TOKENS = 1_100
EXPECTED_SEVEN_DAY_TOKENS = 4_500


def test_usage_history_combines_authoritative_daily_buckets() -> None:
    """Verify the behavior described by this test."""
    analytics_a: JsonObject = {
        "token_usage_updated_at": (NOW - timedelta(minutes=2)).isoformat(),
        "token_usage": {
            "summary": {"lifetime_tokens": 20_000},
            "daily_usage_buckets": [
                {"start_date": "2026-07-09", "tokens": 1_000},
                {"start_date": "2026-07-10", "tokens": 2_000},
                {"start_date": "2026-07-11", "tokens": 500},
            ],
        },
        "reset_credits_updated_at": (NOW - timedelta(minutes=2)).isoformat(),
        "reset_credits": {"available_count": 0, "credits": []},
        "errors": {},
    }
    analytics_b: JsonObject = {
        "token_usage_updated_at": (NOW - timedelta(minutes=3)).isoformat(),
        "token_usage": {
            "summary": {"lifetime_tokens": 30_000},
            "daily_usage_buckets": [
                {"start_date": "2026-07-09", "tokens": 400},
                {"start_date": "2026-07-11", "tokens": 600},
            ],
        },
        "reset_credits_updated_at": (NOW - timedelta(minutes=3)).isoformat(),
        "reset_credits": {"available_count": 0, "credits": []},
        "errors": {},
    }

    snapshot = build_dashboard_snapshot(
        [
            account_fixture("a@example.com", analytics=analytics_a),
            account_fixture("b@example.com", analytics=analytics_b),
        ],
        now=NOW,
        stale_after_seconds=600,
        analytics_stale_after_seconds=1800,
        min_five_hour_remaining_percent=10,
    )

    history = snapshot["usage_history"]
    verify(history["provider_granularity"] == "daily")
    verify(history["granularity"] == "hour")
    verify(history["point_count"] == EXPECTED_HISTORY_POINT_COUNT)
    verify(history["accounts_reporting"] == EXPECTED_REPORTING_ACCOUNT_COUNT)
    by_date: dict[str, int] = {}
    for point in history["combined"]:
        day = point["at"][:10]
        by_date[day] = by_date.get(day, 0) + point["tokens"]
    verify(by_date["2026-07-09"] == EXPECTED_JULY_NINTH_TOKENS)
    verify(by_date["2026-07-10"] == EXPECTED_JULY_TENTH_TOKENS)
    verify(by_date["2026-07-11"] == EXPECTED_JULY_ELEVENTH_TOKENS)
    verify(history["summary"]["seven_day_tokens"] == EXPECTED_SEVEN_DAY_TOKENS)
    verify(history["summary"]["observed_share_percent"] == 0)
    verify(len(history["series"]) == EXPECTED_REPORTING_ACCOUNT_COUNT)


def test_reset_bank_exposes_dates_but_not_provider_ids_or_private_copy() -> None:
    """Verify the behavior described by this test."""
    analytics: JsonObject = {
        "token_usage_updated_at": NOW.isoformat(),
        "token_usage": {"summary": {}, "daily_usage_buckets": []},
        "reset_credits_updated_at": NOW.isoformat(),
        "reset_credits": {
            "available_count": 1,
            "credits": [
                {
                    "id": "must-not-escape-credit-id",
                    "reset_type": "weekly",
                    "status": "available",
                    "granted_at": "2026-07-10T08:00:00Z",
                    "expires_at": "2026-07-18T08:00:00Z",
                    "title": "Weekly reset",
                    "description": "must-not-escape-provider-copy",
                },
            ],
        },
        "errors": {},
    }

    snapshot = build_dashboard_snapshot(
        [account_fixture("bank@example.com", analytics=analytics)],
        now=NOW,
        stale_after_seconds=600,
        analytics_stale_after_seconds=1800,
        min_five_hour_remaining_percent=10,
    )

    bank = snapshot["reset_bank"]
    verify(bank["total_available"] == 1)
    verify(
        bank["details"]
        == [
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
    )
    encoded = json.dumps(snapshot)
    verify("must-not-escape-credit-id" not in encoded)
    verify("must-not-escape-provider-copy" not in encoded)
