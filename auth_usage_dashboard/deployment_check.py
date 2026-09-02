from __future__ import annotations

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


def main() -> None:
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise AssertionError("capacity response must be an object")
    validate_capacity_payload(payload)


if __name__ == "__main__":
    main()
