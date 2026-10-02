# Copyright (c) 2026 PitchAI. All rights reserved.
"""Threshold evaluation and display for the existing host-health snapshot."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, TypedDict, Unpack

from .cycle_values import coerce_optional_float, required_float

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject, JsonValue


class HostLimits(TypedDict):
    """The five explicit optional thresholds accepted by the existing caller."""

    disk_used_percent_max: float | None
    mem_used_percent_max: float | None
    swap_used_percent_max: float | None
    cpu_used_percent_max: float | None
    load1_per_cpu_max: float | None


def format_percent(value: JsonValue) -> str:
    """Return the existing percentage display, or n/a for nonnumeric input."""
    converted = coerce_optional_float(value)
    return f"{converted:.1f}%" if converted is not None else "n/a"


def worst_disk(snapshot: JsonObject) -> tuple[str | None, float | None]:
    """Return the first largest valid disk reading, preserving iteration ties."""
    disks = snapshot.get("disk")
    worst_path = None
    worst_pct = None
    if isinstance(disks, dict):
        for path, info in disks.items():
            if not isinstance(info, dict):
                continue
            value = coerce_optional_float(info.get("used_percent"))
            if value is not None and (worst_pct is None or value > worst_pct):
                worst_path, worst_pct = path, value
    return worst_path, worst_pct


def collect_host_health_violations(
    snap: JsonObject,
    **limits: Unpack[HostLimits],
) -> list[str]:
    """Return threshold violations in the original disk/memory/swap/CPU/load order."""
    violations: list[str] = []
    disk_used_percent_max = limits["disk_used_percent_max"]
    if disk_used_percent_max is not None:
        path, percent = worst_disk(snap)
        if percent is not None and percent >= float(disk_used_percent_max):
            violations.append(f"Disk {path}: {format_percent(percent)} >= {format_percent(disk_used_percent_max)}")
    for field, label, maximum in (
        ("mem_used_percent", "Memory", limits["mem_used_percent_max"]),
        ("swap_used_percent", "Swap", limits["swap_used_percent_max"]),
        ("cpu_used_percent", "CPU", limits["cpu_used_percent_max"]),
    ):
        if maximum is None:
            continue
        value = coerce_optional_float(snap.get(field))
        if value is not None and value >= float(maximum):
            violations.append(f"{label}: {format_percent(value)} >= {format_percent(maximum)}")
    load1_per_cpu_max = limits["load1_per_cpu_max"]
    if load1_per_cpu_max is not None:
        value = coerce_optional_float(snap.get("load1_per_cpu"))
        if value is not None and value >= float(load1_per_cpu_max):
            violations.append(f"Load1/CPU: {value:.2f} >= {float(load1_per_cpu_max):.2f}")
    return violations


def build_host_health_alert_message(
    *,
    violations: list[str],
    snap: JsonObject,
    down_after_failures: int,
    fail_streak: int,
) -> str:
    """Return the unchanged bounded host alert text without performing delivery."""
    lines = ["Monitor warning: host health thresholds exceeded ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.append("")
    lines.extend(f"- {violation}" for violation in violations[:10])
    extra: list[str] = []
    path, percent = worst_disk(snap)
    if path and percent is not None:
        extra.append(f"Disk worst: {path} {format_percent(percent)}")
    for field, label in (("mem_used_percent", "Mem"), ("swap_used_percent", "Swap"), ("cpu_used_percent", "CPU")):
        value = snap.get(field)
        if value is not None:
            extra.append(f"{label} used: {format_percent(value)}")
    load1, load_per_cpu = snap.get("load1"), snap.get("load1_per_cpu")
    with suppress(TypeError, ValueError, OverflowError):
        if load1 is not None:
            load_text = f"Load: {required_float(load1):.1f}"
            if load_per_cpu is not None:
                load_text += f" (per_cpu={required_float(load_per_cpu):.2f})"
            extra.append(load_text)
    if extra:
        lines.append("")
        lines.extend(extra[:6])
    return "\n".join(lines).strip()
