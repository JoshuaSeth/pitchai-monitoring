# Copyright (c) 2026 PitchAI. All rights reserved.
"""Summarize registry responses without treating unavailable input as healthy."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from .dashboard_records import array_or_empty, integer
from .dashboard_values import safe_int, safe_timestamp

if TYPE_CHECKING:
    from domain_checks.config_values import ConfigValue

    from .dashboard_records import Record


def summarize_e2e(e2e_status_summary: Record | None, *, now_ts: float) -> Record:
    """Keep enabled-test selection, fallback status and original last-run age.

    Returns:
        The existing unavailable, healthy or attention summary.
    """
    if not isinstance(e2e_status_summary, dict) or e2e_status_summary.get("ok") is not True:
        return {
            "status": "unavailable", "total_tests": None, "passing_tests": None, "failing_tests": None,
            "disabled_tests": None, "latest_run_at_ts": None, "latest_run_age_seconds": None, "problems": [],
        }
    tests = array_or_empty(e2e_status_summary.get("tests"))
    records = [test for test in tests if isinstance(test, dict)]
    enabled_tests = [test for test in records if integer(test.get("enabled", 1) or 0) == 1]
    problems: list[ConfigValue] = []
    latest_run_at_ts: float | None = None
    for test in enabled_tests:
        finished_at_ts = safe_timestamp(test.get("last_finished_at_ts"))
        if finished_at_ts is not None:
            latest_run_at_ts = finished_at_ts if latest_run_at_ts is None else max(latest_run_at_ts, finished_at_ts)
        effective_ok = 1
        value = test.get("effective_ok")
        with suppress(TypeError, ValueError):
            effective_ok = integer(value if value is not None else 1)
        if effective_ok != 0:
            continue
        problems.append({
            "test_id": str(test.get("test_id") or ""), "test_name": str(test.get("test_name") or "Unnamed E2E test"),
            "base_url": str(test.get("base_url") or ""), "fail_streak": safe_int(test.get("fail_streak")) or 0,
            "last_status": str(test.get("last_status") or "unknown"), "last_finished_at_ts": finished_at_ts,
        })
    total_tests = len(enabled_tests)
    failing_tests = len(problems)
    age = max(0.0, float(now_ts) - latest_run_at_ts) if latest_run_at_ts is not None else None
    return {
        "status": "attention" if failing_tests else "healthy", "total_tests": total_tests,
        "passing_tests": max(0, total_tests - failing_tests), "failing_tests": failing_tests,
        "disabled_tests": max(0, len(tests) - total_tests), "latest_run_at_ts": latest_run_at_ts,
        "latest_run_age_seconds": age, "problems": problems,
    }
