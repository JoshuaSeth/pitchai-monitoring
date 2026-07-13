from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from auth_usage_dashboard.capacity import build_dashboard_snapshot, parse_account


UTC = timezone.utc
NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)


def _account(
    label: str,
    *,
    availability: str = "available",
    enabled: bool = True,
    five_used: float | None = 40,
    five_reset: datetime | None = None,
    weekly_used: float | None = 20,
    weekly_reset: datetime | None = None,
    last_probe: datetime | None = None,
    credits: object | None = None,
    analytics: object | None = None,
) -> dict[str, object]:
    five_reset = five_reset or NOW + timedelta(hours=3)
    weekly_reset = weekly_reset or NOW + timedelta(days=6)
    last_probe = last_probe or NOW - timedelta(seconds=30)
    primary: dict[str, object] = {
        "limit_window_seconds": 18_000,
        "reset_at": five_reset.isoformat(),
    }
    secondary: dict[str, object] = {
        "limit_window_seconds": 604_800,
        "reset_at": weekly_reset.isoformat(),
    }
    if five_used is not None:
        primary["used_percent"] = five_used
    if weekly_used is not None:
        secondary["used_percent"] = weekly_used
    state: dict[str, object] = {
        "availability": availability,
        "last_probe_at": last_probe.isoformat(),
        "refresh_token": "must-not-escape",
        "usage": {
            "email": label,
            "plan_type": "pro",
            "rate_limit": {
                "primary_window": primary,
                "secondary_window": secondary,
            },
            "rate_limit_reset_credits": credits
            if credits is not None
            else {"available_count": 2},
        },
    }
    if analytics is not None:
        state["analytics"] = analytics
    return {
        "metadata": {
            "account_id": f"id-{label}",
            "label": label,
            "enabled": enabled,
            "broker_secret": "must-not-escape",
        },
        "state": state,
        "auth_json": {"access_token": "must-not-escape"},
    }


def _parse(raw: dict[str, object]) -> dict[str, object]:
    return parse_account(
        raw,
        now=NOW,
        stale_after_seconds=600,
        min_five_hour_remaining_percent=10,
    )


@pytest.mark.parametrize(
    ("raw", "status", "selectable"),
    [
        (_account("available@example.com"), "available", True),
        (_account("disabled@example.com", enabled=False), "disabled", False),
        (
            _account("invalid@example.com", availability="auth_invalid"),
            "auth_invalid",
            False,
        ),
        (
            _account(
                "weekly@example.com", availability="rate_limited", weekly_used=100
            ),
            "weekly_limited",
            False,
        ),
        (
            _account("five@example.com", availability="rate_limited", five_used=100),
            "five_hour_limited",
            False,
        ),
        (
            _account("floor@example.com", availability="available", five_used=90),
            "five_hour_limited",
            False,
        ),
    ],
)
def test_account_status_classification(
    raw: dict[str, object], status: str, selectable: bool
) -> None:
    account = _parse(raw)
    assert account["status"] == status
    assert account["selectable_now"] is selectable


def test_expired_provider_reset_is_unknown_until_fresh_probe() -> None:
    raw = _account(
        "expired@example.com",
        availability="rate_limited",
        five_used=100,
        five_reset=NOW - timedelta(seconds=1),
    )

    account = _parse(raw)

    assert account["status"] == "unknown"
    assert account["status_reason"] == "Reset is due; awaiting a fresh provider state"


def test_single_weekly_primary_window_is_not_mislabeled_as_five_hour() -> None:
    raw = _account("weekly-only@example.com", weekly_used=0)
    rate_limit = raw["state"]["usage"]["rate_limit"]
    rate_limit["primary_window"] = rate_limit.pop("secondary_window")

    account = _parse(raw)

    assert account["status"] == "available"
    assert account["five_hour"]["reported"] is False
    assert account["five_hour"]["remaining_percent"] is None
    assert account["five_hour"]["window_seconds"] is None
    assert account["weekly"]["reported"] is True
    assert account["weekly"]["remaining_percent"] == 100


def test_windows_are_classified_by_duration_when_provider_order_is_reversed() -> None:
    raw = _account("reversed@example.com", five_used=25, weekly_used=40)
    rate_limit = raw["state"]["usage"]["rate_limit"]
    rate_limit["primary_window"], rate_limit["secondary_window"] = (
        rate_limit["secondary_window"],
        rate_limit["primary_window"],
    )

    account = _parse(raw)

    assert account["five_hour"]["remaining_percent"] == 75
    assert account["weekly"]["remaining_percent"] == 60


def test_reset_credit_details_support_provider_field_names_and_dates() -> None:
    raw = _account(
        "credits@example.com",
        credits={
            "availableCount": 1,
            "credits": [
                {
                    "resetType": "primary",
                    "status": "available",
                    "grantedAt": "2026-07-10T08:00:00Z",
                    "expiresAt": "2026-07-12T08:00:00Z",
                    "title": "Five-hour reset",
                }
            ],
        },
    )

    credits = _parse(raw)["reset_credits"]

    assert credits["available_count"] == 1
    assert credits["dates_available"] is True
    assert credits["details"][0]["reset_type"] == "primary"
    assert credits["details"][0]["granted_at"] == "2026-07-10T08:00:00Z"
    assert credits["details"][0]["expires_at"] == "2026-07-12T08:00:00Z"


def test_forecast_counts_current_headroom_and_resets_inside_horizon() -> None:
    available = _account(
        "available@example.com",
        five_used=40,
        five_reset=NOW + timedelta(hours=3),
    )
    limited = _account(
        "limited@example.com",
        availability="rate_limited",
        five_used=100,
        five_reset=NOW + timedelta(minutes=30),
    )

    snapshot = build_dashboard_snapshot(
        [available, limited],
        now=NOW,
        stale_after_seconds=600,
        min_five_hour_remaining_percent=10,
    )
    hour = next(item for item in snapshot["forecasts"] if item["key"] == "hour")

    assert snapshot["summary"]["usable_now"] == 1
    assert hour["capacity_points"] == 160
    assert hour["account_equivalents"] == 1.6
    assert hour["maximum_points"] == 300
    assert hour["capacity_percent"] == 53.3
    assert hour["five_hour_resets"] == 1
    assert hour["contributing_accounts"] == 2


def test_missing_five_hour_windows_are_unavailable_not_zero_capacity() -> None:
    accounts = [
        _account("a@example.com", weekly_used=0),
        _account("b@example.com", weekly_used=100),
    ]
    for raw in accounts:
        rate_limit = raw["state"]["usage"]["rate_limit"]
        rate_limit["primary_window"] = rate_limit.pop("secondary_window")

    snapshot = build_dashboard_snapshot(
        accounts,
        now=NOW,
        stale_after_seconds=600,
        min_five_hour_remaining_percent=10,
    )

    assert snapshot["summary"]["window_aggregates"]["five_hour"] == {
        "measurement_status": "unavailable",
        "reporting_accounts": 0,
        "unknown_accounts": 2,
        "remaining_points": None,
        "maximum_known_points": None,
        "remaining_percent": None,
    }
    assert snapshot["summary"]["window_aggregates"]["weekly"]["remaining_percent"] == 50
    assert snapshot["summary"]["capacity_basis"] == {
        "key": "weekly",
        "label": "Weekly",
        "reporting_accounts": 2,
        "eligible_accounts": 2,
        "measurement_status": "complete",
    }
    assert all(
        item["measurement_status"] == "complete" for item in snapshot["forecasts"]
    )
    assert all(item["basis_key"] == "weekly" for item in snapshot["forecasts"])
    assert all(item["capacity_percent"] == 50 for item in snapshot["forecasts"])
    assert snapshot["runout_forecast"]["data_available"] is True
    assert snapshot["runout_forecast"]["capacity_basis"]["key"] == "weekly"
    assert len(snapshot["events"]) == 2
    assert all(item["kind"] == "weekly_reset" for item in snapshot["events"])
    assert snapshot["summary"]["next_useful_capacity_label"] == "b@example.com"
    assert any(item["code"] == "five_hour_unreported" for item in snapshot["warnings"])


def test_stale_available_account_is_not_counted_as_usable_capacity() -> None:
    stale = _account("stale@example.com", last_probe=NOW - timedelta(minutes=20))

    snapshot = build_dashboard_snapshot(
        [stale],
        now=NOW,
        stale_after_seconds=600,
        min_five_hour_remaining_percent=10,
    )

    assert snapshot["accounts"][0]["status"] == "available"
    assert snapshot["accounts"][0]["stale"] is True
    assert snapshot["summary"]["usable_now"] == 0
    assert any(item["code"] == "stale" for item in snapshot["warnings"])
    assert all(item["capacity_points"] is None for item in snapshot["forecasts"])
    assert all(item["measurement_status"] == "unavailable" for item in snapshot["forecasts"])


def test_dashboard_snapshot_does_not_expose_raw_auth_or_broker_identifiers() -> None:
    snapshot = build_dashboard_snapshot(
        [_account("operator@example.com")],
        now=NOW,
        stale_after_seconds=600,
        min_five_hour_remaining_percent=10,
    )
    encoded = json.dumps(snapshot, sort_keys=True)

    assert "must-not-escape" not in encoded
    assert "auth_json" not in encoded
    assert "access_token" not in encoded
    assert "refresh_token" not in encoded
    assert "broker_secret" not in encoded
    assert "id-operator@example.com" not in encoded


def test_usage_history_combines_authoritative_daily_buckets() -> None:
    analytics_a = {
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
    analytics_b = {
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
            _account("a@example.com", analytics=analytics_a),
            _account("b@example.com", analytics=analytics_b),
        ],
        now=NOW,
        stale_after_seconds=600,
        analytics_stale_after_seconds=1800,
        min_five_hour_remaining_percent=10,
    )

    history = snapshot["usage_history"]
    assert history["provider_granularity"] == "daily"
    assert history["granularity"] == "hour"
    assert history["point_count"] == 168
    assert history["accounts_reporting"] == 2
    by_date: dict[str, int] = {}
    for point in history["combined"]:
        day = point["at"][:10]
        by_date[day] = by_date.get(day, 0) + point["tokens"]
    assert by_date["2026-07-09"] == 1_400
    assert by_date["2026-07-10"] == 2_000
    assert by_date["2026-07-11"] == 1_100
    assert history["summary"]["seven_day_tokens"] == 4_500
    assert history["summary"]["observed_share_percent"] == 0
    assert len(history["series"]) == 2


def test_reset_bank_exposes_dates_but_not_provider_ids_or_private_copy() -> None:
    analytics = {
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
                }
            ],
        },
        "errors": {},
    }

    snapshot = build_dashboard_snapshot(
        [_account("bank@example.com", analytics=analytics)],
        now=NOW,
        stale_after_seconds=600,
        analytics_stale_after_seconds=1800,
        min_five_hour_remaining_percent=10,
    )

    bank = snapshot["reset_bank"]
    assert bank["total_available"] == 1
    assert bank["details"] == [
        {
            "account_label": "bank@example.com",
            "reset_type": "weekly",
            "status": "available",
            "title": "Weekly reset",
            "granted_at": "2026-07-10T08:00:00Z",
            "expires_at": "2026-07-18T08:00:00Z",
            "expires_in_seconds": 590_400,
        }
    ]
    encoded = json.dumps(snapshot)
    assert "must-not-escape-credit-id" not in encoded
    assert "must-not-escape-provider-copy" not in encoded
