# Copyright (c) 2026 PitchAI. All rights reserved.
"""Deterministic monitor state and inventory for dashboard browser tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from e2e_registry.models import JsonObject


def dashboard_monitor_state(now: float) -> JsonObject:
    """Build healthy monitor state with one recent recovered incident.

    Returns:
        The deterministic persisted monitor state.
    """
    return {
        "version": 5,
        "history_ok_mode": "effective",
        "last_ok": {"a.example": True},
        "fail_streak": {"a.example": 0},
        "success_streak": {"a.example": 12},
        "history": {
            "a.example": [
                [now - 120, True, 120.0, 420.0, 200],
                [now - 60, True, 140.0, 450.0, 200],
                [now, True, 110.0, 400.0, 200],
            ],
        },
        "signal_history": {
            "browser": [[now - 60, 1, 0, 0], [now, 1, 0, 0]],
            "host_health": [
                [now - 60, 1, 55.0, 0.0, 12.0, 0.7, 42.0, 0],
                [now, 1, 56.0, 0.0, 13.0, 0.8, 43.0, 0],
            ],
            "performance": [[now - 60, 1, 0], [now, 1, 0]],
            "slo": [[now, 1, 0]],
            "red": [[now, 1, 0]],
            "tls": [[now, 1, 0]],
            "dns": [[now, 1, 0]],
            "container_health": [[now, 1, 0]],
            "proxy": [[now, 1, 0]],
            "meta": [[now, 1, 0]],
        },
        "dispatch_history": [
            {
                "ts": now - 30,
                "state_key": "host_health",
                "title": "Host health degraded",
                "queue_state": "processed",
                "ui_url": "https://dispatch.pitchai.net/ui/runs/example",
                "ok": True,
                "agent_message": "Root cause: test data. Suggested: observe only.",
            },
        ],
        "dispatch_last": {
            "host_health": {
                "ts": now - 30,
                "state_key": "host_health",
                "queue_state": "processed",
                "ui_url": "https://dispatch.pitchai.net/ui/runs/example",
                "ok": True,
                "agent_message": "Root cause: test data. Suggested: observe only.",
            },
        },
        "events": [
            {
                "ts": now - 30,
                "kind": "host_health_degraded",
                "violations": ["CPU: 95% > 80%"],
            },
            {"ts": now - 10, "kind": "domain_up", "domain": "a.example"},
        ],
        "host_last_snapshot": {
            "mem_used_percent": 56.0,
            "swap_used_percent": 0.0,
            "cpu_used_percent": 13.0,
            "load1_per_cpu": 0.8,
            "disk": {"/": {"used_percent": 43.0}},
        },
        "browser_degraded_active": False,
        "browser_degraded_first_seen_ts": 0.0,
        "browser_launch_last_error": None,
        "browser_degraded_last_notice_ts": 0.0,
        "host_health": {"last_ok": True, "fail_streak": 0, "success_streak": 10},
        "performance": {"last_ok": True, "fail_streak": 0, "success_streak": 10},
        "slo": {"last_ok": True, "fail_streak": 0, "success_streak": 10},
        "red": {"last_ok": True, "fail_streak": 0, "success_streak": 10},
        "tls": {
            "last_ok": True,
            "fail_streak": 0,
            "success_streak": 10,
            "last_run_ts": now,
        },
        "dns": {
            "last_ok": True,
            "fail_streak": 0,
            "success_streak": 10,
            "last_run_ts": now,
            "last_ips": {},
        },
        "container_health": {
            "last_ok": True,
            "fail_streak": 0,
            "success_streak": 10,
            "last_run_ts": now,
            "restart_counts": {},
        },
        "proxy": {"last_ok": True, "fail_streak": 0, "success_streak": 10},
        "meta": {
            "last_ok": True,
            "fail_streak": 0,
            "success_streak": 10,
            "state_write_fail_streak": 0,
        },
    }


def dashboard_monitor_config() -> JsonObject:
    """Build a two-domain inventory with disabled and retired coverage.

    Returns:
        The deterministic monitoring configuration.
    """
    return {
        "interval_seconds": 60,
        "history": {"retention_days": 14},
        "performance": {"http_elapsed_ms_max": 1500, "browser_elapsed_ms_max": 4000},
        "inventory": {
            "version": 1,
            "reviewed_at": "2026-08-24",
            "authoritative_sources": ["test fixture"],
        },
        "domain_groups": {
            "core": {
                "label": "PitchAI core",
                "description": "Primary platform routes",
                "order": 10,
            },
            "clients": {
                "label": "Client systems",
                "description": "Client-owned deployments",
                "order": 20,
            },
        },
        "domains": [
            {
                "domain": "a.example",
                "label": "Primary test route",
                "group": "core",
                "environment": "production",
                "kind": "application",
                "sources": ["test fixture"],
            },
            {
                "domain": "b.example",
                "label": "Disabled client route",
                "group": "clients",
                "environment": "staging",
                "kind": "application",
                "sources": ["test fixture"],
                "disabled": True,
                "disabled_reason": "temporary",
            },
        ],
        "retired_domains": [
            {
                "domain": "old.example",
                "classification": "retired",
                "reason": "test-only retired route",
                "sources": ["test fixture"],
            },
        ],
    }
