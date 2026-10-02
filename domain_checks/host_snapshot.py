# Copyright (c) 2026 PitchAI. All rights reserved.
"""Assemble host diagnostics without inventing missing operating-system data."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from .host_readings import (
    compute_cpu_used_percent,
    disk_usage_percent,
    load_average,
    read_linux_meminfo_kb,
    read_linux_proc_stat_cpu_total_idle,
)

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject


def _used_percent(total: int | None, available: int | None) -> float | None:
    """Return memory/swap use only when both fields and a positive total exist."""
    if total is not None and total > 0 and available is not None:
        return round((1.0 - (available / float(total))) * 100.0, 3)
    return None


def _disk_snapshot(disk_paths: list[str]) -> JsonObject:
    """Return readable disk percentages in configured path order."""
    disk: JsonObject = {}
    for path in disk_paths:
        cleaned = str(path or "").strip()
        if not cleaned or not Path(cleaned).exists():
            continue
        disk_pct = disk_usage_percent(cleaned)
        if disk_pct is not None:
            disk[cleaned] = {"used_percent": disk_pct}
    return disk


def _cpu_snapshot(cpu_prev_total: int, cpu_prev_idle: int) -> JsonObject:
    """Return CPU use and the next baseline without inventing a first delta."""
    cpu_used_pct = None
    cpu_cur = read_linux_proc_stat_cpu_total_idle()
    cpu_prev_total = int(cpu_prev_total) if cpu_prev_total else 0
    cpu_prev_idle = int(cpu_prev_idle) if cpu_prev_idle else 0
    cpu_cur_total = cpu_cur_idle = None
    if cpu_cur is not None:
        cpu_cur_total, cpu_cur_idle = cpu_cur
        if cpu_prev_total > 0 and cpu_prev_idle > 0:
            cpu_used_pct = compute_cpu_used_percent(
                prev_total=cpu_prev_total,
                prev_idle=cpu_prev_idle,
                cur_total=cpu_cur_total,
                cur_idle=cpu_cur_idle,
            )
    return {
        "cpu_used_percent": cpu_used_pct,
        "cpu_prev_total_next": cpu_cur_total,
        "cpu_prev_idle_next": cpu_cur_idle,
    }


def _load_snapshot() -> JsonObject:
    """Return load and normalize it only when a positive CPU count exists."""
    load1 = load5 = load15 = None
    averages = load_average()
    if averages is not None:
        load1, load5, load15 = (float(value) for value in averages)
    cpu_count = os.cpu_count() or 0
    load1_per_cpu = round(load1 / float(cpu_count), 3) if load1 is not None and cpu_count > 0 else None
    return {
        "cpu_count": cpu_count,
        "load1": load1,
        "load5": load5,
        "load15": load15,
        "load1_per_cpu": load1_per_cpu,
    }


def collect_host_snapshot(*, disk_paths: list[str], cpu_prev_total: int, cpu_prev_idle: int) -> JsonObject:
    """Return the existing JSON snapshot, keeping CPU baselines separate from use."""
    meminfo = read_linux_meminfo_kb()
    memory_total, memory_available = meminfo.get("MemTotal"), meminfo.get("MemAvailable")
    swap_total, swap_free = meminfo.get("SwapTotal"), meminfo.get("SwapFree")
    # Preserve the original read order: memory, configured disks, CPU, then load.
    disks = _disk_snapshot(disk_paths)
    cpu = _cpu_snapshot(cpu_prev_total, cpu_prev_idle)
    load = _load_snapshot()
    return {
        "mem_total_kb": memory_total,
        "mem_available_kb": memory_available,
        "mem_used_percent": _used_percent(memory_total, memory_available),
        "swap_total_kb": swap_total,
        "swap_free_kb": swap_free,
        "swap_used_percent": _used_percent(swap_total, swap_free),
        "disk": disks,
        **cpu,
        **load,
    }
