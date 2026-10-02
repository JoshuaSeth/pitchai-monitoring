# Copyright (c) 2026 PitchAI. All rights reserved.
"""Best-effort operating-system readings for the existing host diagnostics."""

from __future__ import annotations

import os
import shutil
from contextlib import suppress
from pathlib import Path

from .cycle_values import coerce_int

_CPU_IDLE_INDEX = 3
_CPU_IOWAIT_INDEX = 4


def read_linux_meminfo_kb() -> dict[str, int]:
    """Return available memory fields, omitting absent or malformed readings."""
    raw = ""
    # File absence and read/encoding errors mean this optional reading is absent.
    with suppress(OSError, UnicodeError):
        raw = Path("/proc/meminfo").read_text(encoding="utf-8")
    values: dict[str, int] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        parts = rest.strip().split()
        if parts:
            with suppress(ValueError):
                values[key.strip()] = int(parts[0])
    return values


def read_linux_proc_stat_cpu_total_idle() -> tuple[int, int] | None:
    """Return aggregate CPU jiffies, or None when no usable line exists."""
    raw = ""
    with suppress(OSError, UnicodeError):
        raw = Path("/proc/stat").read_text(encoding="utf-8")
    for line in raw.splitlines():
        if line.startswith("cpu "):
            values = [coerce_int(part) for part in line.split()[1:]]
            if len(values) <= _CPU_IDLE_INDEX:
                return None
            idle = values[_CPU_IDLE_INDEX]
            if len(values) > _CPU_IOWAIT_INDEX:
                idle += values[_CPU_IOWAIT_INDEX]
            return sum(values), idle
    return None


def compute_cpu_used_percent(*, prev_total: int, prev_idle: int, cur_total: int, cur_idle: int) -> float | None:
    """Return bounded CPU use, preserving the unavailable first observation."""
    delta_total = int(cur_total) - int(prev_total)
    delta_idle = int(cur_idle) - int(prev_idle)
    if delta_total <= 0:
        return None
    used = max(0.0, min(100.0, (1.0 - (delta_idle / float(delta_total))) * 100.0))
    return round(used, 3)


def disk_usage_percent(path: str) -> float | None:
    """Return used capacity, or None when the requested reading is unavailable."""
    total, used = 0, 0
    with suppress(OSError, ValueError):
        total, used, _free = shutil.disk_usage(path)
    if total <= 0:
        return None
    return round((used / float(total)) * 100.0, 3)


def load_average() -> tuple[float, float, float] | None:
    """Return load averages, leaving unsupported platforms explicitly absent."""
    with suppress(OSError, AttributeError):
        return os.getloadavg()
    return None


def format_browser_health_hint() -> str:
    """Return the existing compact memory/load diagnostic when memory is known."""
    info = read_linux_meminfo_kb()
    if not info:
        return ""
    values: dict[str, str] = {}
    for key in ("MemAvailable", "SwapTotal", "SwapFree"):
        values[key] = str(int(info[key] / 1024)) if key in info else "?"
    swap_total, swap_free = values["SwapTotal"], values["SwapFree"]
    swap_used = str(int(swap_total) - int(swap_free)) if "?" not in {swap_total, swap_free} else "?"
    averages = load_average()
    load = "?"
    if averages is not None:
        values_formatted = (f"{value:.1f}" for value in averages)
        load = "/".join(values_formatted)
    return f"mem_avail_mb={values['MemAvailable']} swap_used_mb={swap_used}/{swap_total} load={load}"
