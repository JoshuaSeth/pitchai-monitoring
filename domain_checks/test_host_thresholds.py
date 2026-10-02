# Copyright (c) 2026 PitchAI. All rights reserved.
"""Synthetic threshold and presentation regressions without an outgoing route."""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from .dft_test_support import require
from .host_thresholds import build_host_health_alert_message, collect_host_health_violations, format_percent, worst_disk

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject


class HostThresholdTests(unittest.TestCase):
    """Protect ordering, exact boundaries and incomplete persisted snapshots."""

    @staticmethod
    def test_threshold_equality_and_order() -> None:
        """Equality qualifies, and malformed disks do not affect the first tie."""
        snapshot: JsonObject = {
            "disk": {"first": {"used_percent": 80}, "second": {"used_percent": 80}, "bad": []},
            "mem_used_percent": "90",
            "swap_used_percent": 40,
            "cpu_used_percent": 70,
            "load1_per_cpu": 2,
        }
        result = collect_host_health_violations(
            snapshot,
            disk_used_percent_max=80,
            mem_used_percent_max=90,
            swap_used_percent_max=40,
            cpu_used_percent_max=70,
            load1_per_cpu_max=2,
        )
        require(
            condition=result
            == [
                "Disk first: 80.0% >= 80.0%",
                "Memory: 90.0% >= 90.0%",
                "Swap: 40.0% >= 40.0%",
                "CPU: 70.0% >= 70.0%",
                "Load1/CPU: 2.00 >= 2.00",
            ],
            message="host diagnostic contract changed",
        )

    @staticmethod
    def test_invalid_and_disabled_fields_do_not_invent_violations() -> None:
        """Retained malformed values use their existing omission behavior."""
        snapshot: JsonObject = {
            "disk": [90],
            "mem_used_percent": {},
            "swap_used_percent": "bad",
            "cpu_used_percent": 99,
            "load1_per_cpu": None,
        }
        require(
            condition=not collect_host_health_violations(
                snapshot,
                disk_used_percent_max=0,
                mem_used_percent_max=0,
                swap_used_percent_max=0,
                cpu_used_percent_max=None,
                load1_per_cpu_max=0,
            ),
            message="host diagnostic contract changed",
        )
        require(condition=format_percent({}) == "n/a", message="host diagnostic contract changed")
        require(condition=format_percent("inf") == "inf%", message="host diagnostic contract changed")

    @staticmethod
    def test_nonfinite_first_disk_preserves_existing_comparison() -> None:
        """The refactor leaves unusual persisted numeric semantics unchanged."""
        snapshot: JsonObject = {"disk": {"first": {"used_percent": "nan"}, "second": {"used_percent": 99}}}
        require(condition=worst_disk(snapshot)[0] == "first", message="host diagnostic contract changed")

    @staticmethod
    def test_alert_bounds_and_malformed_load() -> None:
        """Text is built locally and retains the previous prefix and row limits."""
        snapshot: JsonObject = {
            "disk": {"first": {"used_percent": 90}},
            "mem_used_percent": "bad",
            "load1": 4,
            "load1_per_cpu": "bad",
        }
        message = build_host_health_alert_message(
            violations=[f"issue{index}" for index in range(12)],
            snap=snapshot,
            down_after_failures=2,
            fail_streak=3,
        )
        require(condition="Debounce: fail_streak=3/2" in message, message="host diagnostic contract changed")
        require(condition="- issue9" in message, message="host diagnostic contract changed")
        require(condition="issue10" not in message, message="host diagnostic contract changed")
        require(condition="Disk worst: first 90.0%" in message, message="host diagnostic contract changed")
        require(condition="Mem used: n/a" in message, message="host diagnostic contract changed")
        require(condition="Load:" not in message, message="host diagnostic contract changed")
