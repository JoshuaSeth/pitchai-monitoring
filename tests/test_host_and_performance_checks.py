# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tests for test host and performance checks behavior."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from domain_checks.common_check import DomainCheckResult
from domain_checks.main import (
    collect_host_health_violations,
    collect_performance_violations,
    compute_cpu_used_percent,
)
from domain_checks.testing import verify

if TYPE_CHECKING:
    from domain_checks.types import JsonObject

_EXPECTED_CPU_USED_PERCENT = 80.0


def test_compute_cpu_used_percent_basic() -> None:
    """Verify compute cpu used percent basic."""
    used = compute_cpu_used_percent(prev_total=100, prev_idle=10, cur_total=200, cur_idle=30)
    verify(used is not None and math.isclose(used, _EXPECTED_CPU_USED_PERCENT))


def test_compute_cpu_used_percent_zero_or_negative_delta_returns_none() -> None:
    """Verify compute cpu used percent zero or negative delta returns none."""
    verify(compute_cpu_used_percent(prev_total=100, prev_idle=10, cur_total=100, cur_idle=20) is None)
    verify(compute_cpu_used_percent(prev_total=200, prev_idle=10, cur_total=100, cur_idle=20) is None)


def test_collect_host_health_violations_thresholds() -> None:
    """Verify collect host health violations thresholds."""
    snap: JsonObject = {
        "disk": {
            "/": {"used_percent": 90.0},
            "/data": {"used_percent": 70.0},
        },
        "mem_used_percent": 81.0,
        "swap_used_percent": 10.0,
        "cpu_used_percent": 85.0,
        "load1_per_cpu": 2.5,
    }
    violations = collect_host_health_violations(
        snap,
        disk_used_percent_max=80.0,
        mem_used_percent_max=80.0,
        swap_used_percent_max=80.0,
        cpu_used_percent_max=80.0,
        load1_per_cpu_max=2.0,
    )
    disk_violations = [value.startswith("Disk /:") for value in violations]
    memory_violations = [value.startswith("Memory:") for value in violations]
    cpu_violations = [value.startswith("CPU:") for value in violations]
    load_violations = [value.startswith("Load1/CPU:") for value in violations]
    swap_violations = [value.startswith("Swap:") for value in violations]
    verify(any(disk_violations))
    verify(any(memory_violations))
    verify(any(cpu_violations))
    verify(any(load_violations))
    verify(not any(swap_violations))


def test_collect_performance_violations_thresholds_and_overrides() -> None:
    """Verify collect performance violations thresholds and overrides."""
    results = {
        "a.example": DomainCheckResult(
            domain="a.example",
            ok=True,
            reason="ok",
            details={"http_elapsed_ms": 2000.0, "browser_elapsed_ms": 1000.0},
        ),
        "b.example": DomainCheckResult(
            domain="b.example",
            ok=True,
            reason="ok",
            details={"http_elapsed_ms": 100.0, "browser_elapsed_ms": 8000.0},
        ),
        "down.example": DomainCheckResult(
            domain="down.example",
            ok=False,
            reason="http_check_failed",
            details={"http_elapsed_ms": 5000.0, "browser_elapsed_ms": 9999.0},
        ),
    }

    slow = collect_performance_violations(
        results,
        http_elapsed_ms_max=1500.0,
        browser_elapsed_ms_max=4000.0,
        per_domain_overrides={"a.example": {"http_elapsed_ms_max": 2500.0}},
    )
    domains = {str(entry["domain"]) for entry in slow}
    verify("a.example" not in domains)
    verify("b.example" in domains)
    verify("down.example" not in domains)
