from __future__ import annotations

from domain_checks.common_check import DomainCheckResult
from domain_checks.main import (
    _collect_host_health_violations,
    _collect_performance_violations,
    _compute_cpu_used_percent,
)


def test_compute_cpu_used_percent_basic() -> None:
    used = _compute_cpu_used_percent(prev_total=100, prev_idle=10, cur_total=200, cur_idle=30)
    assert used == 80.0


def test_compute_cpu_used_percent_zero_or_negative_delta_returns_none() -> None:
    assert _compute_cpu_used_percent(prev_total=100, prev_idle=10, cur_total=100, cur_idle=20) is None
    assert _compute_cpu_used_percent(prev_total=200, prev_idle=10, cur_total=100, cur_idle=20) is None


def test_collect_host_health_violations_thresholds() -> None:
    snap = {
        "disk": {
            "/": {"used_percent": 90.0},
            "/data": {"used_percent": 70.0},
        },
        "mem_used_percent": 81.0,
        "swap_used_percent": 10.0,
        "cpu_used_percent": 85.0,
        "load1_per_cpu": 2.5,
    }
    violations = _collect_host_health_violations(
        snap,
        disk_used_percent_max=80.0,
        mem_used_percent_max=80.0,
        swap_used_percent_max=80.0,
        cpu_used_percent_max=80.0,
        load1_per_cpu_max=2.0,
    )
    assert any(v.startswith("Disk /:") for v in violations)
    assert any(v.startswith("Memory:") for v in violations)
    assert any(v.startswith("CPU:") for v in violations)
    assert any(v.startswith("Load1/CPU:") for v in violations)
    assert not any(v.startswith("Swap:") for v in violations)


def test_collect_performance_violations_thresholds_and_overrides() -> None:
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

    slow = _collect_performance_violations(
        results,
        http_elapsed_ms_max=1500.0,
        browser_elapsed_ms_max=4000.0,
        per_domain_overrides={"a.example": {"http_elapsed_ms_max": 2500.0}},
    )
    domains = {entry["domain"] for entry in slow}
    assert "a.example" not in domains  # overridden threshold
    assert "b.example" in domains
    assert "down.example" not in domains  # down domains are excluded from perf warnings
