# Copyright (c) 2026 PitchAI. All rights reserved.
"""Proof for the post-deployment capacity payload validator."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import anyio

from ._mobile_test_runtime import RAISES
from ._timeseries_test_fixtures import check, check_equal
from .deployment_check import validate_capacity_payload

if TYPE_CHECKING:
    from .timeseries_types import JsonObject

VALIDATOR_SCRIPT = Path(__file__).with_name("deployment_check.py")
HOURLY_POINTS = 168
MIN_STDIN_PAYLOAD_CHARACTERS = 300_000
LEAK_PROBE = "must-not-pass"


def _payload() -> JsonObject:
    """Return one valid schema-four capacity payload with a large hourly history.

    Returns:
        A payload that must pass deployment validation.
    """
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
            "point_count": HOURLY_POINTS,
            "combined": [{"tokens": 1, "padding": "x" * 2_000} for _ in range(HOURLY_POINTS)],
        },
        "runout_forecast": {
            "horizons": [{}, {}, {}],
            "banked_reset_policy": {"included_as_automatic_capacity": False},
        },
        "reset_bank": {"details": []},
    }


def test_deployment_validator_accepts_schema_four_capacity() -> None:
    """Prove a complete schema-four payload passes validation without raising."""
    payload = _payload()
    validate_capacity_payload(payload)


async def test_large_capacity_payload_is_validated_over_stdin() -> None:
    """Prove the validator script accepts a payload far larger than one pipe buffer."""
    encoded = json.dumps(_payload())
    check(len(encoded) > MIN_STDIN_PAYLOAD_CHARACTERS, "payload exceeds the stdin size under test")

    completed = await anyio.run_process(
        [sys.executable, str(VALIDATOR_SCRIPT)],
        input=encoded.encode(),
        check=False,
    )

    check_equal(completed.returncode, 0, completed.stderr.decode())


def test_deployment_validator_rejects_secret_key_names() -> None:
    """Prove a payload carrying a secret-bearing key fails validation."""
    payload = _payload()
    payload["access_token"] = LEAK_PROBE

    with RAISES(AssertionError):
        validate_capacity_payload(payload)
