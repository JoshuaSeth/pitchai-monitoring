# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock deployment payload validation and secret rejection."""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

from auth_usage_dashboard.deployment_check import main, validate_capacity_payload
from domain_checks.testing import verify

if TYPE_CHECKING:
    import pytest

    from auth_usage_dashboard.json_contract import JsonObject

FORBIDDEN_VALUE = "must-not-pass"
MINIMUM_LARGE_PAYLOAD_LENGTH = 300_000


def _payload() -> JsonObject:
    return {
        "schema_version": 4,
        "summary": {
            "configured_accounts": 8,
            "capacity_basis": {
                "key": "weekly",
                "label": "Weekly",
                "measurement_status": "complete",
            },
            "window_aggregates": {
                "five_hour": {"measurement_status": "unavailable"},
                "weekly": {"measurement_status": "partial"},
            },
        },
        "accounts": [
            {
                "five_hour": {"reported": False},
                "weekly": {"reported": True},
            },
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


def test_deployment_validator_accepts_schema_four_capacity() -> None:
    """Verify the behavior described by this test."""
    payload = _payload()
    validate_capacity_payload(payload)


def test_large_capacity_payload_is_validated_over_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the behavior described by this test."""
    encoded = json.dumps(_payload())
    verify(len(encoded) > MINIMUM_LARGE_PAYLOAD_LENGTH)

    monkeypatch.setattr("sys.stdin", io.StringIO(encoded))
    main()


def test_deployment_validator_rejects_secret_key_names() -> None:
    """Verify the behavior described by this test.

    Raises:
        AssertionError: If the value violates the validation contract.

    """
    payload = _payload()
    payload["access_token"] = FORBIDDEN_VALUE

    try:
        validate_capacity_payload(payload)
    except AssertionError:
        return
    msg = "secret-bearing payload passed deployment validation"
    raise AssertionError(msg)
