# Copyright (c) 2026 PitchAI. All rights reserved.
"""Expose the existing global signal snapshots without changing source state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .dashboard_records import array_or_empty, object_or_empty
from .dashboard_values import safe_float, safe_timestamp

if TYPE_CHECKING:
    from .dashboard_data import MonitorData
    from .dashboard_records import Record

SIGNAL_KEYS = ("host_health", "performance", "slo", "red", "tls", "dns", "container_health", "proxy", "meta")


def summarize_signals(*, data: MonitorData) -> Record:
    """Copy global records and annotate only signals with a final history sample.

    Returns:
        Browser fields, host snapshot and signal copies in their original order.
    """
    state = object_or_empty(data.state or {})
    histories = object_or_empty(state.get("signal_history"))
    signals: Record = {
        "browser": {
            "degraded_active": bool(state.get("browser_degraded_active", False)),
            "degraded_first_seen_ts": safe_float(state.get("browser_degraded_first_seen_ts")),
            "last_notice_ts": safe_float(state.get("browser_degraded_last_notice_ts")),
            "launch_last_error": state.get("browser_launch_last_error"),
        },
        "host_health": dict(object_or_empty(state.get("host_health"))),
        "host_last_snapshot": dict(object_or_empty(state.get("host_last_snapshot"))),
    }
    for key in SIGNAL_KEYS[1:]:
        signals[key] = dict(object_or_empty(state.get(key)))
    for key in SIGNAL_KEYS:
        history = array_or_empty(histories.get(key))
        if history and isinstance(history[-1], list) and history[-1]:
            signal = object_or_empty(signals[key])
            signal["observed_at_ts"] = safe_timestamp(history[-1][0])
    return signals


def signal_display_name(signal: str) -> str:
    """Resolve the existing operator-facing signal labels.

    Returns:
        A known label or the original title-cased underscore fallback.
    """
    labels = {
        "host_health": "Host health", "performance": "Performance", "slo": "SLO", "red": "RED metrics",
        "tls": "TLS", "dns": "DNS", "container_health": "Container health", "proxy": "Reverse proxy",
        "meta": "Monitor integrity", "browser": "Browser checks",
    }
    return labels.get(signal, signal.replace("_", " ").title())
