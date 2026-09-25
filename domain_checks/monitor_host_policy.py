# Copyright (c) 2026 PitchAI. All rights reserved.
"""Host-health threshold policy evaluation."""

from __future__ import annotations

from operator import itemgetter
from typing import TYPE_CHECKING, TypedDict, Unpack

from domain_checks.monitor_values import json_float, json_object

if TYPE_CHECKING:
    from domain_checks.types import JsonObject, JsonValue


class HostThresholds(TypedDict):
    """Optional host-health limits accepted by the public evaluator."""

    disk_used_percent_max: float | None
    mem_used_percent_max: float | None
    swap_used_percent_max: float | None
    cpu_used_percent_max: float | None
    load1_per_cpu_max: float | None


def _format_percent(value: float) -> str:
    return f"{value:.1f}%"


def _numeric(value: JsonValue) -> float | None:
    try:
        return json_float(value)
    except (TypeError, ValueError):
        return None


def _scalar_violation(label: str, value: JsonValue, limit: float | None) -> str | None:
    measured = _numeric(value)
    if limit is None or measured is None or measured < limit:
        return None
    return f"{label}: {_format_percent(measured)} >= {_format_percent(limit)}"


def _disk_violation(snap: JsonObject, disk_limit: float | None) -> str | None:
    measured_disks: list[tuple[str, float]] = []
    for path, info in json_object(snap.get("disk")).items():
        measured = _numeric(json_object(info).get("used_percent"))
        if measured is not None:
            measured_disks.append((path, measured))
    if disk_limit is None or not measured_disks:
        return None
    worst_path, worst_value = max(measured_disks, key=itemgetter(1))
    if worst_value < disk_limit:
        return None
    return f"Disk {worst_path}: {_format_percent(worst_value)} >= {_format_percent(disk_limit)}"


def _scalar_violations(snap: JsonObject, limits: HostThresholds) -> list[str]:
    configured = (
        ("Memory", "mem_used_percent", limits["mem_used_percent_max"]),
        ("Swap", "swap_used_percent", limits["swap_used_percent_max"]),
        ("CPU", "cpu_used_percent", limits["cpu_used_percent_max"]),
    )
    violations: list[str] = []
    for label, key, limit in configured:
        violation = _scalar_violation(label, snap.get(key), limit)
        if violation is not None:
            violations.append(violation)
    return violations


def collect_host_health_violations(snap: JsonObject, **limits: Unpack[HostThresholds]) -> list[str]:
    """Return all host-health threshold violations.

    Returns:
        Every configured host-health threshold violation.
    """
    violations = _scalar_violations(snap, limits)
    disk_violation = _disk_violation(snap, limits["disk_used_percent_max"])
    if disk_violation is not None:
        violations.insert(0, disk_violation)
    load = _numeric(snap.get("load1_per_cpu"))
    load_limit = limits["load1_per_cpu_max"]
    if load is not None and load_limit is not None and load >= load_limit:
        violations.append(f"Load1/CPU: {load:.2f} >= {load_limit:.2f}")
    return violations
