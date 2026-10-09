# Copyright (c) 2026 PitchAI. All rights reserved.
"""Retained subcheck dashboard fixture values."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .monitor_dashboard_fixture import fixture_config, fixture_snapshot

if TYPE_CHECKING:
    from e2e_registry.dashboard_data import MonitorData


def make_subcheck_fixture(now: float) -> MonitorData:
    """Build the unchanged subcheck observation fixture.

    Returns:
        The original synthetic observations and any external test status.
    """
    return fixture_snapshot(
        state={
            "updated_at": now,
            "history": {"dispatch.pitchai.net": [[now, True, 100.0, 200.0, 200]]},
            "last_ok": {"dispatch.pitchai.net": True},
            "fail_streak": {"dispatch.pitchai.net": 0},
            "success_streak": {"dispatch.pitchai.net": 4},
            "api_contract": {
                "last_ok": {"dispatch.pitchai.net": False},
                "fail_streak": {"dispatch.pitchai.net": 2},
                "success_streak": {"dispatch.pitchai.net": 0},
                "last_run_ts": {"dispatch.pitchai.net": now},
            },
        },
        config=fixture_config(
            groups={"operations": {"label": "Operations", "description": "Operator services", "order": 10}},
            domains=[
                {
                    "domain": "dispatch.pitchai.net",
                    "label": "Dispatcher",
                    "group": "operations",
                    "environment": "internal",
                    "kind": "application",
                    "sources": ["test fixture"],
                },
            ],
            reviewed_at="2026-08-24",
        ),
        now=now,
    )
