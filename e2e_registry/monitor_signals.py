# Copyright (c) 2026 PitchAI. All rights reserved.
"""Global monitoring-signal summaries and event classification."""

from __future__ import annotations

from typing import TYPE_CHECKING

from e2e_registry.monitor_values import monitor_mapping, safe_float, safe_timestamp

if TYPE_CHECKING:
    from e2e_registry.monitor_types import MonitorData, MonitorRecord


def _signal_history_timestamp(data: MonitorData, signal: str) -> float | None:
    histories = monitor_mapping(data.state.get("signal_history"))
    history = histories.get(signal)
    if not isinstance(history, list) or not history:
        return None
    latest = history[-1]
    if not isinstance(latest, list | tuple) or not latest:
        return None
    return safe_timestamp(latest[0])


def summarize_signals(*, data: MonitorData) -> MonitorRecord:
    """Return the current state of each dashboard-wide monitoring signal."""
    state = data.state
    signals: MonitorRecord = {
        "browser": {
            "degraded_active": bool(state.get("browser_degraded_active", False)),
            "degraded_first_seen_ts": safe_float(state.get("browser_degraded_first_seen_ts")),
            "last_notice_ts": safe_float(state.get("browser_degraded_last_notice_ts")),
            "launch_last_error": state.get("browser_launch_last_error"),
        },
        "host_health": dict(monitor_mapping(state.get("host_health"))),
        "host_last_snapshot": dict(monitor_mapping(state.get("host_last_snapshot"))),
        "performance": dict(monitor_mapping(state.get("performance"))),
        "slo": dict(monitor_mapping(state.get("slo"))),
        "red": dict(monitor_mapping(state.get("red"))),
        "tls": dict(monitor_mapping(state.get("tls"))),
        "dns": dict(monitor_mapping(state.get("dns"))),
        "container_health": dict(monitor_mapping(state.get("container_health"))),
        "proxy": dict(monitor_mapping(state.get("proxy"))),
        "meta": dict(monitor_mapping(state.get("meta"))),
    }
    for key, value in signals.items():
        if key in {"browser", "host_last_snapshot"}:
            continue
        signal_state = monitor_mapping(value)
        observed_at_ts = _signal_history_timestamp(data, key)
        if observed_at_ts is not None:
            signal_state["observed_at_ts"] = observed_at_ts
    return signals


def event_kind_is_problem(kind: str) -> bool:
    """Return whether an event kind represents a new problem."""
    normalized = str(kind or "").strip().lower()
    return normalized.endswith(("_down", "_degraded", "_failed", "_failure", "_error", "_unhealthy"))


def event_kind_is_recovery(kind: str) -> bool:
    """Return whether an event kind represents a recovery."""
    normalized = str(kind or "").strip().lower()
    return normalized.endswith(("_up", "_recovered", "_healthy"))


def signal_display_name(signal: str) -> str:
    """Return an operator-facing label for a global signal."""
    return {
        "host_health": "Host health",
        "performance": "Performance",
        "slo": "SLO",
        "red": "RED metrics",
        "tls": "TLS",
        "dns": "DNS",
        "container_health": "Container health",
        "proxy": "Reverse proxy",
        "meta": "Monitor integrity",
        "browser": "Browser checks",
    }.get(signal, signal.replace("_", " ").title())
