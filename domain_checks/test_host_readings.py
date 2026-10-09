# Copyright (c) 2026 PitchAI. All rights reserved.
"""Synthetic OS observations for the existing host diagnostic contract."""

from __future__ import annotations

import math
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from . import host_readings, host_snapshot
from .dft_test_support import require


class HostReadingsTests(unittest.TestCase):
    """Exercise unavailable data and counter boundaries without reading a host."""

    @staticmethod
    def test_memory_omits_malformed_fields() -> None:
        """Missing and invalid fields remain absent instead of looking healthy."""
        raw = "MemTotal: 8192 kB\nMemAvailable: bad\nSwapFree:\nno-colon\n X : -1 kB\n"
        with patch.object(Path, "read_text", return_value=raw):
            require(
                condition=host_readings.read_linux_meminfo_kb() == {"MemTotal": 8192, "X": -1},
                message="host diagnostic contract changed",
            )
        with patch.object(Path, "read_text", side_effect=OSError("synthetic")):
            require(condition=not host_readings.read_linux_meminfo_kb(), message="missing memory became a sample")

    @staticmethod
    def test_cpu_retains_first_aggregate_and_bad_field_zero() -> None:
        """Per-core lines do not replace the aggregate; partial aggregates fail."""
        raw = "cpu0 5 6 7 8\ncpu 10 bad 20 30 40 50\ncpu 999 999 999 999\n"
        with patch.object(Path, "read_text", return_value=raw):
            require(
                condition=host_readings.read_linux_proc_stat_cpu_total_idle() == (150, 70),
                message="host diagnostic contract changed",
            )
        for raw in ("cpu 1 2 3\n", "cpu0 1 2 3 4\n", ""):
            with patch.object(Path, "read_text", return_value=raw):
                require(
                    condition=host_readings.read_linux_proc_stat_cpu_total_idle() is None,
                    message="host diagnostic contract changed",
                )
        with patch.object(Path, "read_text", side_effect=OSError("synthetic")):
            require(
                condition=host_readings.read_linux_proc_stat_cpu_total_idle() is None,
                message="host diagnostic contract changed",
            )

    @staticmethod
    def test_counter_reset_and_clamping() -> None:
        """A reset is unavailable; inconsistent positive deltas stay bounded."""
        require(
            condition=host_readings.compute_cpu_used_percent(prev_total=200, prev_idle=20, cur_total=100, cur_idle=10)
            is None,
            message="host diagnostic contract changed",
        )
        high = host_readings.compute_cpu_used_percent(prev_total=100, prev_idle=20, cur_total=200, cur_idle=0)
        low = host_readings.compute_cpu_used_percent(prev_total=100, prev_idle=20, cur_total=200, cur_idle=200)
        require(condition=high is not None and math.isclose(high, 100.0), message="upper CPU clamp changed")
        require(condition=low is not None and math.isclose(low, 0.0), message="lower CPU clamp changed")

    @staticmethod
    def test_capacity_and_load_read_failures() -> None:
        """Unavailable counters are not converted into a zero-percent sample."""
        with patch.object(shutil, "disk_usage", return_value=(100, 31, 69)):
            used = host_readings.disk_usage_percent("/synthetic")
            require(
                condition=used is not None and math.isclose(used, 31.0),
                message="host diagnostic contract changed",
            )
        with patch.object(shutil, "disk_usage", side_effect=OSError("synthetic")):
            require(
                condition=host_readings.disk_usage_percent("/synthetic") is None,
                message="host diagnostic contract changed",
            )
        with patch.object(os, "getloadavg", side_effect=AttributeError("synthetic")):
            require(condition=host_readings.load_average() is None, message="host diagnostic contract changed")

    @staticmethod
    def test_browser_hint_retains_truncation_and_missing_load() -> None:
        """Memory uses original integer MiB presentation and unknown load text."""
        memory = {"MemAvailable": 2049, "SwapTotal": 4097, "SwapFree": 1025}
        with (
            patch.object(host_readings, "read_linux_meminfo_kb", return_value=memory),
            patch.object(host_readings, "load_average", return_value=None),
        ):
            require(
                condition=host_readings.format_browser_health_hint() == "mem_avail_mb=2 swap_used_mb=3/4 load=?",
                message="host diagnostic contract changed",
            )


class HostSnapshotTests(unittest.TestCase):
    """Keep sample assembly isolated from every real operating-system input."""

    @staticmethod
    def test_first_cpu_sample_is_baseline_only() -> None:
        """A first sample publishes its next counters without CPU-use evidence."""
        memory = {"MemTotal": 1000, "MemAvailable": 250, "SwapTotal": 0, "SwapFree": 0}
        with (
            patch.object(host_snapshot, "read_linux_meminfo_kb", return_value=memory),
            patch.object(host_snapshot, "read_linux_proc_stat_cpu_total_idle", return_value=(200, 40)),
            patch.object(host_snapshot, "load_average", return_value=(4.0, 2.0, 1.0)),
            patch.object(os, "cpu_count", return_value=2),
            patch.object(Path, "exists", return_value=True),
            patch.object(host_snapshot, "disk_usage_percent", return_value=40.0),
        ):
            snapshot = host_snapshot.collect_host_snapshot(
                disk_paths=["", " /synthetic "],
                cpu_prev_total=0,
                cpu_prev_idle=0,
            )
        require(condition=snapshot["cpu_used_percent"] is None, message="host diagnostic contract changed")
        expected_total = 200
        require(condition=snapshot["cpu_prev_total_next"] == expected_total, message="next CPU baseline changed")
        memory_used, load = snapshot["mem_used_percent"], snapshot["load1_per_cpu"]
        require(condition=isinstance(memory_used, float) and math.isclose(memory_used, 75.0),
                message="memory fraction changed")
        require(condition=snapshot["swap_used_percent"] is None, message="host diagnostic contract changed")
        require(condition=isinstance(load, float) and math.isclose(load, 2.0), message="per-CPU load changed")
        require(
            condition=snapshot["disk"] == {"/synthetic": {"used_percent": 40.0}},
            message="host diagnostic contract changed",
        )

    @staticmethod
    def test_missing_readings_preserve_unavailable_fields() -> None:
        """An absent host reading cannot become a healthy zero-traffic analogue."""
        with (
            patch.object(host_snapshot, "read_linux_meminfo_kb", return_value={}),
            patch.object(host_snapshot, "read_linux_proc_stat_cpu_total_idle", return_value=None),
            patch.object(host_snapshot, "load_average", return_value=None),
            patch.object(os, "cpu_count", return_value=None),
            patch.object(Path, "exists", return_value=False),
            patch.object(host_snapshot, "disk_usage_percent") as disk_read,
        ):
            snapshot = host_snapshot.collect_host_snapshot(
                disk_paths=["/synthetic"],
                cpu_prev_total=100,
                cpu_prev_idle=10,
            )
        disk_read.assert_not_called()
        require(condition=snapshot["disk"] == {}, message="host diagnostic contract changed")
        require(condition=snapshot["cpu_count"] == 0, message="host diagnostic contract changed")
        for key in ("mem_used_percent", "cpu_used_percent", "cpu_prev_total_next", "load1_per_cpu"):
            require(condition=snapshot[key] is None, message="host diagnostic contract changed")
