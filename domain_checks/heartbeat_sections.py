# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing bounded host and performance heartbeat sections."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .cycle_values import coerce_optional_float
from .host_thresholds import format_percent, worst_disk
from .message_performance import format_ms

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject


def host_lines(snapshot: JsonObject, violations: list[str] | None) -> list[str]:
    """Return host readings in the original order, omitting invalid optional load."""
    status = f"DEGRADED ({len(violations)} issue(s))" if violations else "OK"
    lines = ["", "Host health:", f"- Status: {status}"]
    path, percent = worst_disk(snapshot)
    if path and percent is not None:
        lines.append(f"- Disk: {path} {format_percent(percent)}")
    for key, label in (
        ("mem_used_percent", "Mem used"), ("swap_used_percent", "Swap used"), ("cpu_used_percent", "CPU used"),
    ):
        if snapshot.get(key) is not None:
            lines.append(f"- {label}: {format_percent(snapshot.get(key))}")
    lines.extend(_load_lines(snapshot))
    if violations:
        lines.append("- Violations:")
        lines.extend(f"  - {value}" for value in violations[:5])
    return lines


def _load_lines(snapshot: JsonObject) -> list[str]:
    load = coerce_optional_float(snapshot.get("load1"))
    if load is None:
        return []
    if snapshot.get("load1_per_cpu") is None:
        return [f"- Load: {load:.1f}"]
    per_cpu = coerce_optional_float(snapshot.get("load1_per_cpu"))
    if per_cpu is None:
        return []
    return [f"- Load: {load:.1f} (per_cpu={per_cpu:.2f})"]


def performance_lines(slow: list[JsonObject]) -> list[str]:
    """Return the original first-five performance rows, preserving input order."""
    if not slow:
        return ["", "Performance: OK"]
    lines = ["", f"Performance: DEGRADED (slow_domains={len(slow)})"]
    for entry in slow[:5]:
        http_ms = format_ms(entry.get("http_ms"))
        browser_ms = format_ms(entry.get("browser_ms"))
        lines.append(f"- {entry.get('domain')}: {http_ms} / {browser_ms}")
    return lines
