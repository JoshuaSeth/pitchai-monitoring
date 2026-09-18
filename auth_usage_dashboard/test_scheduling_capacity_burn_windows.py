# Copyright (c) 2026 PitchAI. All rights reserved.
"""Focused scheduling-capacity burn-window and routing contract tests."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import TYPE_CHECKING, final

from ._scheduling_capacity_test_fixtures import operator_snapshot, routing_inventory
from ._timeseries_test_fixtures import (
    UsageTimeSeriesCase,
    check,
    check_close,
    check_equal,
    require_array,
)
from .scheduling_capacity import build_scheduling_capacity_snapshot
from .scheduling_capacity_burn_windows import capacity_burn_window
from .scheduling_capacity_check import validate_scheduling_capacity_payload
from .timeseries_types import require_object

if TYPE_CHECKING:
    from .timeseries_types import JsonObject


@final
class SchedulingCapacityBurnWindowsTest(UsageTimeSeriesCase):
    """Prove burn windows and broker routing metadata remain non-blocking."""

    @staticmethod
    def test_missing_routing_marker_uses_broker_standard_tier_default() -> None:
        """Treat an omitted broker marker as standard, matching live routing."""
        inventory = routing_inventory()
        metadata = require_object(inventory[1].get("metadata"), description="metadata")
        _ = metadata.pop("last_resort")

        payload = build_scheduling_capacity_snapshot(
            operator_snapshot(),
            raw_accounts=inventory,
            usage_samples=[],
        )
        capacity = require_object(payload.get("capacity"), description="capacity")
        protected = require_object(
            payload.get("protected_last_resort"),
            description="protected capacity",
        )
        actual = (
            capacity.get("eligible_accounts"),
            capacity.get("remaining_points"),
            protected.get("classification_status"),
            protected.get("unclassified_account_count"),
        )
        check_equal(
            actual,
            (3, 163.5, "complete", 0),
            "omitted last-resort markers must follow the broker's standard default",
        )
        validate_scheduling_capacity_payload(payload)

    @staticmethod
    def test_malformed_routing_marker_remains_an_explicit_diagnostic() -> None:
        """Keep malformed explicit metadata visible without suppressing capacity."""
        inventory = routing_inventory()
        metadata = require_object(inventory[1].get("metadata"), description="metadata")
        metadata["last_resort"] = "false"

        payload = build_scheduling_capacity_snapshot(
            operator_snapshot(),
            raw_accounts=inventory,
            usage_samples=[],
        )
        capacity = require_object(payload.get("capacity"), description="capacity")
        protected = require_object(
            payload.get("protected_last_resort"),
            description="protected capacity",
        )
        actual = (
            capacity.get("eligible_accounts"),
            capacity.get("remaining_points"),
            protected.get("classification_status"),
            protected.get("unclassified_account_count"),
        )
        check_equal(
            actual,
            (3, 163.5, "partial", 1),
            "malformed explicit metadata must remain diagnosable",
        )
        validate_scheduling_capacity_payload(payload)

    @staticmethod
    def test_validator_rejects_mislabeled_burn_window_duration() -> None:
        """Bind each named window to its exact wall-clock duration."""
        payload = build_scheduling_capacity_snapshot(
            operator_snapshot(),
            raw_accounts=routing_inventory(),
            usage_samples=[],
        )
        windows = require_object(
            payload.get("burn_windows"),
            description="burn windows",
        )
        last_hour = require_object(windows.get("last_hour"), description="last hour")
        last_hour["starts_at"] = last_hour["ends_at"]

        def validate_invalid_payload() -> None:
            """Execute the malformed payload through the contract validator."""
            validate_scheduling_capacity_payload(payload)

        validation_case = unittest.FunctionTestCase(validate_invalid_payload)
        result = unittest.TestResult()
        validation_case.run(result)

        check_equal(result.testsRun, 1, "validation test count")
        check_equal(len(result.errors), 0, "validation unexpected errors")
        check_equal(len(result.failures), 1, "validation failure count")
        check(
            "last_hour chronology" in result.failures[0][1],
            "validator must identify the mislabeled last-hour chronology",
        )

    @staticmethod
    def test_window_skips_resets_regressions_and_long_sample_gaps() -> None:
        """Count only continuous, same-reset native burn intervals."""
        account = require_object(
            require_array(operator_snapshot().get("accounts"), "accounts")[0],
            description="account",
        )
        samples = [
            _window_sample(
                "2026-08-28T10:00:00Z",
                used=90.0,
                reset="11:00",
                tokens=100,
            ),
            _window_sample("2026-08-28T10:05:00Z", used=1.0, reset="12:00", tokens=200),
            _window_sample("2026-08-28T10:35:00Z", used=2.0, reset="12:00", tokens=500),
            _window_sample("2026-08-28T10:40:00Z", used=4.0, reset="12:00", tokens=600),
        ]

        window = capacity_burn_window(
            [account],
            samples=samples,
            now=datetime(2026, 8, 28, 10, 40, tzinfo=UTC),
            window_hours=1,
        )

        check_close(window.get("capacity_points"), 2.0, "continuous burn points")
        check_close(
            window.get("capacity_points_per_hour"),
            24.0,
            "continuous burn rate",
        )
        check_equal(window.get("provider_tokens"), 200, "continuous provider tokens")
        check_equal(window.get("sample_count"), 4, "contributing samples")
        check_close(window.get("coverage_percent"), 8.3, "continuous coverage")


def _window_sample(
    at: str,
    *,
    used: float,
    reset: str,
    tokens: int,
) -> JsonObject:
    return {
        "at": at,
        "accounts": {
            "private-one@pitchai.net": {
                "five_used_percent": used,
                "five_reset_at": f"2026-08-28T{reset}:00Z",
                "token_date": "2026-08-28",
                "tokens_today": tokens,
            },
        },
    }
