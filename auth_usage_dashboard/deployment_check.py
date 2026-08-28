from __future__ import annotations

import argparse
import json
import sys
from typing import Any


FORBIDDEN_KEYS = (
    "auth_json",
    "access_token",
    "refresh_token",
    "admin_token",
    "credit_id",
)


def validate_capacity_payload(payload: dict[str, Any]) -> None:
    assert payload["schema_version"] == 4
    assert payload["summary"]["configured_accounts"] > 0
    basis = payload["summary"]["capacity_basis"]
    assert basis["key"] in {"five_hour", "weekly", None}
    assert basis["measurement_status"] in {"complete", "partial", "unavailable"}
    for key in ("five_hour", "weekly"):
        aggregate = payload["summary"]["window_aggregates"][key]
        assert aggregate["measurement_status"] in {"complete", "partial", "unavailable"}
    for account in payload["accounts"]:
        assert isinstance(account["five_hour"]["reported"], bool)
        assert isinstance(account["weekly"]["reported"], bool)
    assert payload["usage_history"]["provider_granularity"] == "daily"
    assert payload["usage_history"]["granularity"] == "hour"
    assert payload["usage_history"]["point_count"] == 168
    assert "combined" in payload["usage_history"]
    assert len(payload["runout_forecast"]["horizons"]) == 3
    assert (
        payload["runout_forecast"]["banked_reset_policy"][
            "included_as_automatic_capacity"
        ]
        is False
    )
    assert "details" in payload["reset_bank"]
    encoded = json.dumps(payload)
    assert not any(forbidden in encoded for forbidden in FORBIDDEN_KEYS)


def validate_scheduling_capacity_payload(payload: dict[str, Any]) -> None:
    assert payload["schema_version"] == 2
    assert payload["status"] in {"available", "degraded", "unavailable"}
    assert set(payload["source"]) == {
        "stale",
        "error",
        "history_error",
        "newest_probe_at",
        "freshness_seconds",
    }
    assert payload["capacity"]["basis_key"] in {"five_hour", "weekly", None}
    assert payload["capacity"]["measurement_status"] in {
        "complete",
        "partial",
        "unavailable",
    }
    assert payload["capacity"]["timeline_status"] in {
        "complete",
        "partial",
        "unavailable",
    }
    assert payload["burn"]["confidence"] in {
        "high",
        "medium",
        "low",
        "unavailable",
    }
    assert payload["token_burn"]["diagnostic_only"] is True
    assert payload["banked_resets"]["included_as_automatic_capacity"] is False
    assert payload["methodology"]["identity_scope"] == "aggregate_only"
    assert all("account_label" not in event for event in payload["automatic_resets"])
    assert all("account_label" not in bucket for bucket in payload["expiry_buckets"])
    encoded = json.dumps(payload)
    assert "@" not in encoded
    assert not any(forbidden in encoded for forbidden in FORBIDDEN_KEYS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--contract",
        choices=("capacity", "scheduling-capacity"),
        default="capacity",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise AssertionError("capacity response must be an object")
    if args.contract == "scheduling-capacity":
        validate_scheduling_capacity_payload(payload)
    else:
        validate_capacity_payload(payload)


if __name__ == "__main__":
    main()
