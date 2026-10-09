# Copyright (c) 2026 PitchAI. All rights reserved.
"""Retained operator dashboard fixture values."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .monitor_dashboard_fixture import fixture_config, fixture_snapshot

if TYPE_CHECKING:
    from e2e_registry.dashboard_data import MonitorData
    from e2e_registry.dashboard_records import Record


def make_operator_fixture(now: float) -> tuple[MonitorData, Record]:
    """Build the unchanged operator observation fixture.

    Returns:
        The original synthetic observations and any external test status.
    """
    data = fixture_snapshot(
        state={
            "updated_at": now - 400,
            "history": {
                "down.pitchai.net": [[now - 120, True, 100.0, 300.0, 200], [now - 60, False, 900.0, 1800.0, 503]],
            },
            "last_ok": {"down.pitchai.net": False},
            "fail_streak": {"down.pitchai.net": 2},
            "success_streak": {"down.pitchai.net": 0},
            "host_health": {"last_ok": False, "fail_streak": 3, "success_streak": 0},
            "events": [
                {"ts": now - 90000, "kind": "domain_down", "domain": "old.pitchai.net"},
                {"ts": now - 100, "kind": "domain_down", "domain": "down.pitchai.net"},
                {"ts": now - 50, "kind": "proxy_recovered"},
            ],
        },
        config=fixture_config(
            groups={"core": {"label": "PitchAI core", "description": "Primary platform routes", "order": 10}},
            domains=[
                {
                    "domain": "down.pitchai.net",
                    "label": "Down test route",
                    "group": "core",
                    "environment": "production",
                    "kind": "application",
                    "sources": ["test fixture"],
                },
            ],
            reviewed_at="2026-08-24",
        ),
        now=now,
    )
    e2e: Record = {
        "ok": True,
        "total_tests": 2,
        "failing_tests": 1,
        "tests": [
            {
                "test_id": "passing",
                "test_name": "Passing route",
                "base_url": "https://passing.pitchai.net",
                "enabled": 1,
                "effective_ok": 1,
                "last_status": "pass",
                "last_finished_at_ts": now - 20,
            },
            {
                "test_id": "failing",
                "test_name": "Failing route",
                "base_url": "https://failing.pitchai.net",
                "enabled": 1,
                "effective_ok": 0,
                "fail_streak": 2,
                "last_status": "fail",
                "last_finished_at_ts": now - 10,
            },
        ],
    }
    return (data, e2e)
