# Copyright (c) 2026 PitchAI. All rights reserved.
"""Project retained host and container snapshots into safe dashboard rows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from monitoring_contracts.json_types import (
    bool_value,
    float_value,
    int_value,
    object_list,
    optional_object,
    value_list,
)
from monitoring_contracts.safe_evidence import safe_text_excerpt

if TYPE_CHECKING:
    from monitoring_contracts.json_types import JsonObject, JsonValue

_HISTORY_WINDOW_SECONDS = 86_400.0
_MIN_SAMPLE_FIELDS = 2
_MEMORY_FIELDS = 3
_SWAP_FIELDS = 4
_CPU_FIELDS = 5
_LOAD_FIELDS = 6
_DISK_FIELDS = 7
_VIOLATION_FIELDS = 8


def host_trend(
    state: JsonObject,
    *,
    now_ts: float,
) -> tuple[list[JsonValue], float | None]:
    """Build bounded 24-hour host trend rows and their latest timestamp.

    Returns:
        Downsampled host-health points and their newest retained timestamp.
    """
    signal_history = optional_object(state.get("signal_history"))
    history = value_list(signal_history.get("host_health"))
    rows: list[list[JsonValue]] = []
    observed_at: float | None = None
    for raw in history:
        sample = value_list(raw)
        timestamp = float_value(sample[0]) if sample else None
        if timestamp is None:
            continue
        observed_at = timestamp if observed_at is None else max(observed_at, timestamp)
        if timestamp >= now_ts - _HISTORY_WINDOW_SECONDS and len(sample) >= _MIN_SAMPLE_FIELDS:
            rows.append(sample)
    step = max(1, (len(rows) + 47) // 48)
    trend: list[JsonValue] = [
        {
            "observed_at_ts": float_value(sample[0]),
            "ok": bool_value(sample[1]),
            "memory_used_pct": float_value(sample[2]) if len(sample) >= _MEMORY_FIELDS else None,
            "swap_used_pct": float_value(sample[3]) if len(sample) >= _SWAP_FIELDS else None,
            "cpu_used_pct": float_value(sample[4]) if len(sample) >= _CPU_FIELDS else None,
            "load1_per_cpu": float_value(sample[5]) if len(sample) >= _LOAD_FIELDS else None,
            "worst_disk_used_pct": float_value(sample[6]) if len(sample) >= _DISK_FIELDS else None,
            "violation_count": int_value(sample[7]) if len(sample) >= _VIOLATION_FIELDS else None,
        }
        for sample in rows[::step]
    ]
    return trend, observed_at


def disk_rows(snapshot: JsonObject) -> list[JsonObject]:
    """Return sanitized disk utilization rows."""
    rows: list[JsonObject] = []
    for path, raw in sorted(optional_object(snapshot.get("disk")).items()):
        disk = optional_object(raw)
        rows.append(
            {
                "path": safe_text_excerpt(path, max_chars=120),
                "used_percent": float_value(disk.get("used_percent")),
                "total_bytes": int_value(disk.get("total_bytes")),
                "used_bytes": int_value(disk.get("used_bytes")),
                "free_bytes": int_value(disk.get("free_bytes")),
            },
        )
    return rows


def container_rows(state: JsonObject) -> list[JsonObject]:
    """Return at most 500 sanitized container status rows."""
    rows: list[JsonObject] = []
    for raw in object_list(state.get("container_snapshot"))[:500]:
        running = bool_value(raw.get("running"))
        health = safe_text_excerpt(raw.get("health_status"), max_chars=80)
        restart_increase = int_value(raw.get("restart_increase"))
        error = safe_text_excerpt(raw.get("error"), max_chars=240)
        if error or running is False or (health and health != "healthy") or (restart_increase or 0) > 0:
            status = "degraded"
        elif running is True:
            status = "healthy"
        else:
            status = "unknown"
        rows.append(
            {
                "name": safe_text_excerpt(raw.get("name"), max_chars=160) or "unnamed",
                "container_id": safe_text_excerpt(raw.get("container_id"), max_chars=24),
                "status": status,
                "running": running,
                "docker_status": safe_text_excerpt(raw.get("status"), max_chars=160),
                "health_status": health,
                "restart_count": int_value(raw.get("restart_count")),
                "restart_increase": restart_increase,
                "oom_killed": bool_value(raw.get("oom_killed")),
                "exit_code": int_value(raw.get("exit_code")),
                "error": error,
            },
        )
    return rows
