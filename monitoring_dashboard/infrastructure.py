# Copyright (c) 2026 PitchAI. All rights reserved.
"""Aggregate retained host and container data for the Infrastructure tab."""

from __future__ import annotations

from typing import TYPE_CHECKING

from monitoring_contracts.json_types import (
    bool_value,
    float_value,
    int_value,
    json_object,
    optional_object,
    text_value,
)

from .infrastructure_projection import (
    container_rows,
    disk_rows,
    host_trend,
)

if TYPE_CHECKING:
    from monitoring_contracts.json_types import JsonObject


def _freshness_state(
    *,
    observed_at: float | None,
    now_ts: float,
    stale_after: float | None,
    has_data: bool,
    summary_only: bool = False,
) -> tuple[str, float | None]:
    age = max(0.0, now_ts - observed_at) if observed_at is not None else None
    if not has_data or observed_at is None:
        return "missing", age
    if stale_after is None:
        return ("summary_missing_config" if summary_only else "missing_config"), age
    if age is not None and age > stale_after:
        return ("stale_summary" if summary_only else "stale"), age
    return ("summary_only" if summary_only else "available"), age


def _host_projection(state: JsonObject, config: JsonObject, *, now_ts: float) -> JsonObject:
    host_snapshot = optional_object(state.get("host_last_snapshot"))
    host_state = optional_object(state.get("host_health"))
    host_config = optional_object(config.get("host_health"))
    interval = int_value(config.get("interval_seconds"))
    host_stale_after = float(interval * 3) if interval and interval > 0 else None
    trend, host_observed_at = host_trend(state, now_ts=now_ts)
    host_data_state, host_age = _freshness_state(
        observed_at=host_observed_at,
        now_ts=now_ts,
        stale_after=host_stale_after,
        has_data=bool(host_snapshot),
    )
    return json_object({
        "data_state": host_data_state,
        "observed_at_ts": host_observed_at,
        "age_seconds": host_age,
        "stale_after_seconds": host_stale_after,
        "last_ok": bool_value(host_state.get("last_ok")),
        "fail_streak": int_value(host_state.get("fail_streak")) or 0,
        "metrics": {
            "cpu_used_pct": float_value(host_snapshot.get("cpu_used_percent")),
            "memory_used_pct": float_value(host_snapshot.get("mem_used_percent")),
            "swap_used_pct": float_value(host_snapshot.get("swap_used_percent")),
            "load1": float_value(host_snapshot.get("load1")),
            "load5": float_value(host_snapshot.get("load5")),
            "load15": float_value(host_snapshot.get("load15")),
            "load1_per_cpu": float_value(host_snapshot.get("load1_per_cpu")),
            "cpu_count": int_value(host_snapshot.get("cpu_count")),
        },
        "thresholds": {
            "cpu_used_pct": float_value(host_config.get("cpu_used_percent_max")),
            "memory_used_pct": float_value(host_config.get("mem_used_percent_max")),
            "swap_used_pct": float_value(host_config.get("swap_used_percent_max")),
            "load1_per_cpu": float_value(host_config.get("load1_per_cpu_max")),
            "disk_used_pct": float_value(host_config.get("disk_used_percent_max")),
        },
        "disks": disk_rows(host_snapshot),
        "trend_24h": trend,
    })


def _restart_counts(container_state: JsonObject) -> list[int]:
    counts: list[int] = []
    for value in optional_object(container_state.get("restart_counts")).values():
        count = int_value(value)
        if count is not None and count >= 0:
            counts.append(count)
    return counts


def _container_counts(containers: list[JsonObject], restart_counts: list[int]) -> JsonObject:
    counts: JsonObject = {
        "total": len(containers) if containers else len(restart_counts),
        "healthy": 0,
        "degraded": 0,
        "unknown": 0,
    }
    for item in containers:
        status = text_value(item.get("status"))
        if status in {"healthy", "degraded", "unknown"}:
            counts[status] = (int_value(counts.get(status)) or 0) + 1
    if not containers:
        counts["unknown"] = len(restart_counts)
    return counts


def _container_projection(state: JsonObject, config: JsonObject, *, now_ts: float) -> JsonObject:

    container_state = optional_object(state.get("container_health"))
    container_config = optional_object(config.get("container_health"))
    container_observed_at = float_value(container_state.get("last_run_ts"))
    container_interval = int_value(container_config.get("interval_minutes"))
    container_stale_after: float | None = None
    if container_interval is not None and container_interval > 0:
        container_stale_after = float(max(180, container_interval * 180))
    containers = container_rows(state)
    restart_counts = _restart_counts(container_state)
    summary_only = not containers and bool(restart_counts)
    container_data_state, container_age = _freshness_state(
        observed_at=container_observed_at,
        now_ts=now_ts,
        stale_after=container_stale_after,
        has_data=bool(containers or restart_counts),
        summary_only=summary_only,
    )
    counts = _container_counts(containers, restart_counts)
    return json_object({
        "data_state": container_data_state,
        "observed_at_ts": container_observed_at,
        "age_seconds": container_age,
        "stale_after_seconds": container_stale_after,
        "last_ok": bool_value(container_state.get("last_ok")),
        "fail_streak": int_value(container_state.get("fail_streak")) or 0,
        "counts": counts,
        "restart_total": sum(restart_counts),
        "items": containers,
    })


def build_infrastructure(*, state: JsonObject, config: JsonObject, now_ts: float) -> JsonObject:
    """Build host/container state without triggering any dashboard-side probe.

    Returns:
        Sanitized host, disk, and container status from retained monitor state.
    """
    host = _host_projection(state, config, now_ts=now_ts)
    containers = _container_projection(state, config, now_ts=now_ts)
    counts = optional_object(containers.get("counts"))
    degraded_containers = int_value(counts.get("degraded")) or 0
    if (
        bool_value(host.get("last_ok")) is False
        or bool_value(containers.get("last_ok")) is False
        or degraded_containers
    ):
        overall = "attention"
    elif text_value(host.get("data_state")) != "available" or text_value(containers.get("data_state")) != "available":
        overall = "incomplete"
    else:
        overall = "healthy"
    return json_object({
        "status": overall,
        "host": host,
        "containers": containers,
        "polling": {"source": "existing monitor state", "dashboard_extra_probes": 0},
    })
