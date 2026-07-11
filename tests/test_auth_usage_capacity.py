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
    return {
        "metadata": {
            "account_id": f"id-{label}",
            "label": label,
            "enabled": enabled,
            "broker_secret": "must-not-escape",
        },
        "state": {
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
        },
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
        (_account("invalid@example.com", availability="auth_invalid"), "auth_invalid", False),
        (_account("weekly@example.com", availability="rate_limited", weekly_used=100), "weekly_limited", False),
        (_account("five@example.com", availability="rate_limited", five_used=100), "five_hour_limited", False),
        (_account("floor@example.com", availability="available", five_used=90), "five_hour_limited", False),
    ],
)
def test_account_status_classification(raw: dict[str, object], status: str, selectable: bool) -> None:
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
    assert all(item["capacity_points"] == 0 for item in snapshot["forecasts"])


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
