# Copyright (c) 2026 PitchAI. All rights reserved.
"""Canonical persisted monitor-state schema defaults."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain_checks.types import JsonObject


def _per_domain_state() -> JsonObject:
    return {"last_ok": {}, "fail_streak": {}, "success_streak": {}, "last_run_ts": {}}


def default_monitor_state() -> JsonObject:
    """Build an independent canonical monitor-state value.

    Returns:
        A fresh canonical state payload.
    """
    debounce = {"last_ok": True, "fail_streak": 0, "success_streak": 0}
    return {
        "version": 6,
        "history_ok_mode": "effective",
        "last_ok": {},
        "fail_streak": {},
        "success_streak": {},
        "history": {},
        "signal_history": {},
        "dispatch_history": [],
        "dispatch_last": {},
        "events": [],
        "event_bus_outbox": [],
        "host_last_snapshot": {},
        "browser_degraded_active": False,
        "browser_degraded_first_seen_ts": 0.0,
        "browser_launch_last_error": None,
        "browser_degraded_last_notice_ts": 0.0,
        "host_health": {
            **debounce,
            "cpu_prev_total": 0,
            "cpu_prev_idle": 0,
        },
        "performance": dict(debounce),
        "slo": dict(debounce),
        "tls": {**debounce, "last_run_ts": 0.0},
        "dns": {**debounce, "last_run_ts": 0.0, "last_ips": {}},
        "red": dict(debounce),
        "synthetic": _per_domain_state(),
        "web_vitals": _per_domain_state(),
        "api_contract": _per_domain_state(),
        "container_health": {
            **debounce,
            "last_run_ts": 0.0,
            "restart_counts": {},
        },
        "proxy": dict(debounce),
        "meta": {**debounce, "state_write_fail_streak": 0},
    }
