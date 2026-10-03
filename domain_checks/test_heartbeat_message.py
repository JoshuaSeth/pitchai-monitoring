# Copyright (c) 2026 PitchAI. All rights reserved.
"""Bounded heartbeat text cases with no transport or live observations."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from .common_check import DomainCheckResult
from .dft_test_support import require, require_error
from .domain_entries import normalize_domain_entries
from .heartbeat_external import external_lines
from .heartbeat_message import build_heartbeat_message, format_uptime
from .heartbeat_sections import host_lines

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject, JsonValue


class HeartbeatMessageTests(unittest.TestCase):
    """Exercise optional sections and retained display policies independently."""

    @staticmethod
    def test_dashboard_domain_and_disabled_sections_keep_order() -> None:
        """Sorted domain rows keep dashboard-only labels and one trailing newline."""
        entry = normalize_domain_entries([
            {"domain": "a.invalid", "alert_policy": {"telegram": "dashboard-only", "reason": "fixture"}},
        ])[0]
        now = datetime(2026, 1, 2, tzinfo=UTC)
        healthy = DomainCheckResult("z.invalid", ok=True, reason="ok", details={})
        failed = DomainCheckResult("a.invalid", ok=False, reason="failure", details={"error": "fixture"})
        text = build_heartbeat_message(
            now=now, started_at=now - timedelta(seconds=61), scheduled_label="fixture",
            results={"z.invalid": healthy, "a.invalid": failed},
            domain_entries={entry.domain: entry}, perf_slow=[], disabled_lines=["- paused.invalid: DISABLED"],
        )
        require(condition=text.index("- a.invalid") < text.index("- z.invalid"), message="domain ordering changed")
        require(condition="expected/dashboard only (no Telegram alert)" in text, message="dashboard label omitted")
        require(condition="Performance: OK\n" in text and "Uptime: 1m 01s" in text, message="optional text changed")
        require(condition=text.endswith("- paused.invalid: DISABLED\n") and not text.endswith("\n\n"),
                message="disabled section or newline changed")

    @staticmethod
    def test_host_ties_and_invalid_optional_load() -> None:
        """First disk wins ties and an invalid per-CPU value omits the whole load row."""
        snapshot: JsonObject = {
            "disk": {"first": {"used_percent": 70}, "second": {"used_percent": "70"}},
            "load1": 2, "load1_per_cpu": "invalid", "mem_used_percent": "invalid",
        }
        lines = host_lines(snapshot, [str(index) for index in range(7)])
        require(condition="- Disk: first 70.0%" in lines, message="disk order changed")
        load_rows = [line for line in lines if "- Load:" in line]
        require(condition="- Mem used: n/a" in lines and not load_rows,
                message="invalid optional load became available")
        require(condition=lines[-1] == "  - 4" and "  - 5" not in lines, message="violation prefix changed")

    @staticmethod
    def test_external_limits_stable_ties_and_numeric_failure() -> None:
        """Failure prefixes and elapsed ties retain registry order; bad sort keys fail."""
        indices = range(7)
        names = [f"fixture{index}" for index in indices]
        tests: list[JsonValue] = [{"test_name": name, "effective_ok": 0, "last_elapsed_ms": 10} for name in names]
        lines = external_lines({"total_tests": "7", "failing_tests": "7", "tests": tests})
        require(condition=lines[-3:] == ["  - fixture0: 10ms", "  - fixture1: 10ms", "  - fixture2: 10ms"],
                message="stable slowest prefix changed")
        excess_rows = [line for line in lines if "fixture5" in line]
        require(condition=not excess_rows, message="failure prefix grew")
        with require_error(ValueError, "could not convert"):
            external_lines({"tests": [{"last_elapsed_ms": "invalid"}]})

    @staticmethod
    def test_error_and_uptime_boundaries() -> None:
        """Error details stay capped and backwards time displays zero uptime."""
        lines = external_lines({"ok": False, "error": " " + "x" * 400 + " "})
        require(condition=lines[-1] == "- " + "x" * 300, message="error cap changed")
        require(condition=format_uptime(timedelta(seconds=-1)) == "0m 00s", message="backwards uptime changed")
        require(condition=format_uptime(timedelta(days=1, hours=2, minutes=3)) == "1d 02h 03m",
                message="day uptime changed")
