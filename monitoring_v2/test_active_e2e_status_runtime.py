# Copyright (c) 2026 PitchAI. All rights reserved.
"""Regression coverage for active E2E status reconciliation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .active_e2e_status_runtime import (
    E2ETestStatusProjection,
    project_e2e_test_status,
    reconcile_e2e_status_summary,
)
from .testing_runtime import pytest

if TYPE_CHECKING:
    from .json_types import JsonInput

_EXPECTED_ACTIVE_TESTS = 2


def test_disabled_down_state_does_not_count_as_active_failure() -> None:
    """Exclude retired DOWN state while preserving a real enabled failure."""
    records: JsonInput = [
        {"enabled": 0, "effective_ok": 0},
        {"enabled": 1, "effective_ok": 1},
        {"enabled": 1, "effective_ok": 0},
    ]
    projected = project_e2e_test_status(records)
    expected = E2ETestStatusProjection(active=2, disabled=1, failing=1)
    if projected != expected:
        pytest.fail(f"unexpected E2E status projection: {projected}")


def test_malformed_enabled_state_fails_closed_as_disabled() -> None:
    """Prevent malformed registry state from becoming heartbeat-alertable."""
    records: JsonInput = [{"enabled": "invalid", "effective_ok": 0}]
    projected = project_e2e_test_status(records)
    expected = E2ETestStatusProjection(active=0, disabled=1, failing=0)
    if projected != expected:
        pytest.fail(f"malformed enabled state was not isolated: {projected}")


def test_alert_summary_removes_retired_afas_failure_and_keeps_real_red() -> None:
    """Exclude the exact stale AFAS lane without suppressing genuine RED."""
    summary: JsonInput = {
        "ok": True,
        "total_tests": 3,
        "failing_tests": 2,
        "tests": [
            {
                "test_name": "afasask_gzb_codex_medium_ok_daily",
                "enabled": 0,
                "effective_ok": 0,
            },
            {
                "test_name": "real_production_hotpath_down",
                "enabled": 1,
                "effective_ok": 0,
            },
            {
                "test_name": "healthy_read_path",
                "enabled": 1,
                "effective_ok": 1,
            },
        ],
    }
    reconciled = reconcile_e2e_status_summary(summary)
    expected_names = ["real_production_hotpath_down", "healthy_read_path"]
    visible = reconciled.get("tests")
    names = (
        [record.get("test_name") for record in visible if isinstance(record, dict)]
        if isinstance(visible, list)
        else []
    )
    if names != expected_names:
        pytest.fail(f"unexpected alert-facing tests: {names}")
    if reconciled.get("total_tests") != _EXPECTED_ACTIVE_TESTS or reconciled.get("disabled_tests") != 1:
        pytest.fail(f"unexpected reconciled totals: {reconciled}")
    if reconciled.get("failing_tests") != 1:
        pytest.fail(f"genuine RED failure was not preserved: {reconciled}")
