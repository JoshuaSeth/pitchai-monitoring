from __future__ import annotations

import json

from auth_usage_dashboard.deployment_check import (
    validate_scheduling_capacity_payload,
)
from auth_usage_dashboard.scheduling_capacity import (
    build_scheduling_capacity_snapshot,
)


def _operator_snapshot() -> dict[str, object]:
    return {
        "generated_at": "2026-08-28T12:00:00Z",
        "source": {
            "stale": False,
            "error": None,
            "history_error": None,
            "newest_account_probe_at": "2026-08-28T11:59:30Z",
        },
        "summary": {
            "usable_now": 2,
            "capacity_basis": {
                "key": "five_hour",
                "label": "Five-hour",
                "reporting_accounts": 2,
                "eligible_accounts": 2,
                "measurement_status": "complete",
            },
            "window_aggregates": {
                "five_hour": {
                    "remaining_points": 125.5,
                    "maximum_known_points": 200.0,
                    "remaining_percent": 62.8,
                }
            },
        },
        "usage_history": {
            "summary": {
                "trailing_two_hour_tokens": 42_000,
                "average_hourly_tokens": 18_000,
                "observed_share_percent": 81.5,
            }
        },
        "runout_forecast": {
            "data_available": True,
            "highest_risk": "medium",
            "highest_probability_percent": 31,
            "burn_rate": {
                "capacity_points_per_hour": 12.5,
                "confidence": "high",
                "source": "native_broker_samples",
                "lookback_hours": 2,
                "sample_count": 20,
                "covered_accounts": 2,
                "coefficient_of_variation": 0.2,
            },
            "horizons": [
                {
                    "key": "hour",
                    "horizon_seconds": 3600,
                    "probability_percent": 0,
                    "risk": "low",
                    "expected_runout_at": None,
                    "scheduled_resets": 1,
                    "scheduled_capacity_points": 100,
                    "driver_with_identity": "must not escape",
                }
            ],
        },
        "reset_bank": {"total_available": 3, "details": ["must not escape"]},
        "events": [
            {
                "kind": "five_hour_reset",
                "account_label": "private-one@pitchai.net",
                "at": "2026-08-28T13:00:00Z",
                "capacity_points": 100,
                "restores_selectability": True,
            },
            {
                "kind": "five_hour_reset",
                "account_label": "private-two@pitchai.net",
                "at": "2026-08-28T13:00:00Z",
                "capacity_points": 100,
                "restores_selectability": False,
            },
        ],
        "accounts": [
            {
                "label": "private-one@pitchai.net",
                "email": "private-one@pitchai.net",
                "enabled": True,
                "auth_valid": True,
                "stale": False,
                "selectable_now": True,
                "status": "available",
                "five_hour": {
                    "reported": True,
                    "remaining_percent": 75.5,
                    "reset_at": "2026-08-28T13:00:00Z",
                    "window_seconds": 18_000,
                },
                "weekly": {
                    "reported": True,
                    "remaining_percent": 80.0,
                    "reset_at": "2026-09-03T13:00:00Z",
                    "window_seconds": 604_800,
                },
            },
            {
                "label": "private-two@pitchai.net",
                "email": "private-two@pitchai.net",
                "enabled": True,
                "auth_valid": True,
                "stale": False,
                "selectable_now": False,
                "status": "five_hour_limited",
                "five_hour": {
                    "reported": True,
                    "remaining_percent": 50.0,
                    "reset_at": "2026-08-28T13:00:00Z",
                    "window_seconds": 18_000,
                },
                "weekly": {
                    "reported": True,
                    "remaining_percent": 70.0,
                    "reset_at": "2026-09-03T13:00:00Z",
                    "window_seconds": 604_800,
                },
            },
        ],
    }


def test_scheduler_projection_is_aggregate_only_and_deterministic() -> None:
    snapshot = _operator_snapshot()

    first = build_scheduling_capacity_snapshot(snapshot)
    second = build_scheduling_capacity_snapshot(snapshot)

    assert first == second
    assert first["schema_version"] == 2
    assert first["status"] == "available"
    assert first["source"]["freshness_seconds"] == 30
    assert first["capacity"]["remaining_points"] == 75.5
    assert first["capacity"]["timeline_status"] == "complete"
    assert first["burn"]["capacity_points_per_hour"] == 12.5
    assert first["token_burn"]["diagnostic_only"] is True
    assert first["expiry_buckets"] == [
        {
            "kind": "five_hour_window",
            "at": "2026-08-28T13:00:00Z",
            "in_seconds": 3600,
            "count": 2,
            "remaining_points": 75.5,
        }
    ]
    first_reset = first["automatic_resets"][0]
    assert first_reset == {
        "kind": "five_hour_reset",
        "at": "2026-08-28T13:00:00Z",
        "in_seconds": 3600,
        "expires_at": "2026-08-28T18:00:00Z",
        "count": 2,
        "capacity_points": 200.0,
        "restores_selectability_count": 1,
    }
    assert all(event["kind"] == "five_hour_reset" for event in first["automatic_resets"])
    encoded = json.dumps(first)
    assert "private-one" not in encoded
    assert "private-two" not in encoded
    assert "driver_with_identity" not in encoded
    validate_scheduling_capacity_payload(first)


def test_scheduler_projection_fails_closed_when_measurement_is_missing() -> None:
    snapshot = _operator_snapshot()
    snapshot["summary"]["capacity_basis"] = {
        "key": None,
        "label": None,
        "measurement_status": "unavailable",
    }

    projection = build_scheduling_capacity_snapshot(snapshot)

    assert projection["status"] == "unavailable"
    assert projection["capacity"]["remaining_points"] is None
    assert projection["capacity"]["basis_key"] is None


def test_scheduler_projection_excludes_unselectable_remaining_points() -> None:
    snapshot = _operator_snapshot()
    snapshot["summary"]["usable_now"] = 0
    snapshot["accounts"][0]["selectable_now"] = False
    snapshot["accounts"][0]["status"] = "five_hour_limited"

    projection = build_scheduling_capacity_snapshot(snapshot)

    assert projection["capacity"]["usable_accounts_now"] == 0
    assert projection["capacity"]["remaining_points"] == 0.0


def test_scheduler_projection_uses_only_the_selected_weekly_basis() -> None:
    snapshot = _operator_snapshot()
    snapshot["summary"]["capacity_basis"] = {
        "key": "weekly",
        "label": "Weekly",
        "reporting_accounts": 2,
        "eligible_accounts": 2,
        "measurement_status": "complete",
    }
    snapshot["summary"]["window_aggregates"] = {
        "weekly": {
            "remaining_points": 150.0,
            "maximum_known_points": 200.0,
            "remaining_percent": 75.0,
        },
    }

    projection = build_scheduling_capacity_snapshot(snapshot)

    assert projection["capacity"]["basis_key"] == "weekly"
    assert projection["capacity"]["remaining_points"] == 80.0
    assert projection["expiry_buckets"] == [
        {
            "kind": "weekly_window",
            "at": "2026-09-03T13:00:00Z",
            "in_seconds": 522000,
            "count": 2,
            "remaining_points": 80.0,
        },
    ]
    assert all(event["kind"] == "weekly_reset" for event in projection["automatic_resets"])


def test_scheduler_projection_marks_stale_inputs_degraded() -> None:
    snapshot = _operator_snapshot()
    snapshot["source"]["stale"] = True

    projection = build_scheduling_capacity_snapshot(snapshot)

    assert projection["status"] == "degraded"
    assert projection["source"]["stale"] is True
