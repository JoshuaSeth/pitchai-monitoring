from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from auth_usage_dashboard.deployment_check import validate_capacity_payload


ROOT = Path(__file__).resolve().parents[1]


def _payload() -> dict[str, object]:
    return {
        "schema_version": 3,
        "summary": {
            "configured_accounts": 8,
            "window_aggregates": {
                "five_hour": {"measurement_status": "unavailable"},
                "weekly": {"measurement_status": "partial"},
            },
        },
        "accounts": [
            {
                "five_hour": {"reported": False},
                "weekly": {"reported": True},
            }
        ],
        "usage_history": {
            "provider_granularity": "daily",
            "granularity": "hour",
            "point_count": 168,
            "combined": [{"tokens": 1, "padding": "x" * 2_000} for _ in range(168)],
        },
        "runout_forecast": {
            "horizons": [{}, {}, {}],
            "banked_reset_policy": {"included_as_automatic_capacity": False},
        },
        "reset_bank": {"details": []},
    }


def test_deployment_validator_accepts_schema_three_capacity() -> None:
    validate_capacity_payload(_payload())


def test_large_capacity_payload_is_validated_over_stdin() -> None:
    encoded = json.dumps(_payload())
    assert len(encoded) > 300_000

    result = subprocess.run(
        [sys.executable, str(ROOT / "auth_usage_dashboard" / "deployment_check.py")],
        input=encoded,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_deployment_validator_rejects_secret_key_names() -> None:
    payload = _payload()
    payload["access_token"] = "must-not-pass"

    try:
        validate_capacity_payload(payload)
    except AssertionError:
        return
    raise AssertionError("secret-bearing payload passed deployment validation")
