# Copyright (c) 2026 PitchAI. All rights reserved.
"""Linux host telemetry and monitor threshold evaluation."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from domain_checks.monitor_values import json_int

if TYPE_CHECKING:
    from domain_checks.types import JsonObject

_MIN_CPU_JIFFIES = 4


def read_linux_meminfo_kb() -> dict[str, int]:
    """Read the Linux memory snapshot, returning empty data off Linux.

    Returns:
        Memory counters keyed by their Linux meminfo names.
    """
    try:
        raw = Path("/proc/meminfo").read_text(encoding="utf-8")
    except OSError:
        return {}
    values: dict[str, int] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        parts = rest.strip().split()
        if not parts:
            continue
        try:
            values[key.strip()] = json_int(parts[0])
        except ValueError:
            continue
    return values


def _memory_mb(info: dict[str, int], key: str) -> str:
    value = info.get(key)
    return "?" if value is None else str(int(value / 1024))


def format_browser_health_hint() -> str:
    """Format concise memory, swap, and load diagnostics for browser failures.

    Returns:
        A compact host-health hint, or an empty string off Linux.
    """
    info = read_linux_meminfo_kb()
    if not info:
        return ""
    available = _memory_mb(info, "MemAvailable")
    swap_total = _memory_mb(info, "SwapTotal")
    swap_free = _memory_mb(info, "SwapFree")
    swap_used = "?" if "?" in {swap_total, swap_free} else str(int(swap_total) - int(swap_free))
    try:
        load_values = os.getloadavg()
    except OSError:
        load = "?"
    else:
        load = "/".join(f"{value:.1f}" for value in load_values)
    return f"mem_avail_mb={available} swap_used_mb={swap_used}/{swap_total} load={load}"


def _read_cpu_jiffies() -> tuple[int, int] | None:
    try:
        raw = Path("/proc/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    cpu_line = next((line for line in raw.splitlines() if line.startswith("cpu ")), None)
    if cpu_line is None:
        return None
    try:
        values = [json_int(value) for value in cpu_line.split()[1:]]
    except ValueError:
        return None
    if len(values) < _MIN_CPU_JIFFIES:
        return None
    return sum(values), values[3] + (values[4] if len(values) > _MIN_CPU_JIFFIES else 0)


def compute_cpu_used_percent(
    *,
    prev_total: int,
    prev_idle: int,
    cur_total: int,
    cur_idle: int,
) -> float | None:
    """Calculate CPU use from two aggregate jiffy samples.

    Returns:
        CPU use as a percentage, or ``None`` without elapsed jiffies.
    """
    delta_total = cur_total - prev_total
    if delta_total <= 0:
        return None
    delta_idle = cur_idle - prev_idle
    return round(max(0.0, min(100.0, (1.0 - delta_idle / delta_total) * 100.0)), 3)


def _disk_usage_percent(path: str) -> float | None:
    try:
        total, used, _free = shutil.disk_usage(path)
    except OSError:
        return None
    return None if total <= 0 else round(used / total * 100.0, 3)


def _used_percent(total: int | None, available: int | None) -> float | None:
    if not isinstance(total, int) or total <= 0 or not isinstance(available, int):
        return None
    return round((1.0 - available / total) * 100.0, 3)


def _disk_snapshot(disk_paths: list[str]) -> JsonObject:
    disk: JsonObject = {}
    for path in disk_paths:
        cleaned = path.strip()
        percentage = _disk_usage_percent(cleaned) if cleaned and Path(cleaned).exists() else None
        if percentage is not None:
            disk[cleaned] = {"used_percent": percentage}
    return disk


def _cpu_snapshot(cpu_prev_total: int, cpu_prev_idle: int) -> JsonObject:
    current_cpu = _read_cpu_jiffies()
    current_total, current_idle = current_cpu if current_cpu is not None else (None, None)
    cpu_used = None
    if current_total is not None and current_idle is not None and cpu_prev_total > 0 and cpu_prev_idle > 0:
        cpu_used = compute_cpu_used_percent(
            prev_total=cpu_prev_total,
            prev_idle=cpu_prev_idle,
            cur_total=current_total,
            cur_idle=current_idle,
        )
    return {
        "cpu_used_percent": cpu_used,
        "cpu_prev_total_next": current_total,
        "cpu_prev_idle_next": current_idle,
    }


def _load_snapshot() -> JsonObject:
    try:
        load_values = os.getloadavg()
    except OSError:
        load_values = (None, None, None)
    load1, load5, load15 = load_values
    cpu_count = os.cpu_count() or 0
    return {
        "cpu_count": cpu_count,
        "load1": load1,
        "load5": load5,
        "load15": load15,
        "load1_per_cpu": round(load1 / cpu_count, 3) if load1 is not None and cpu_count else None,
    }


def collect_host_snapshot(*, disk_paths: list[str], cpu_prev_total: int, cpu_prev_idle: int) -> JsonObject:
    """Collect one host-health snapshot and the next CPU baseline.

    Returns:
        The complete host-health snapshot.
    """
    memory = read_linux_meminfo_kb()
    return {
        "mem_total_kb": memory.get("MemTotal"),
        "mem_available_kb": memory.get("MemAvailable"),
        "mem_used_percent": _used_percent(memory.get("MemTotal"), memory.get("MemAvailable")),
        "swap_total_kb": memory.get("SwapTotal"),
        "swap_free_kb": memory.get("SwapFree"),
        "swap_used_percent": _used_percent(memory.get("SwapTotal"), memory.get("SwapFree")),
        "disk": _disk_snapshot(disk_paths),
        **_cpu_snapshot(cpu_prev_total, cpu_prev_idle),
        **_load_snapshot(),
    }
