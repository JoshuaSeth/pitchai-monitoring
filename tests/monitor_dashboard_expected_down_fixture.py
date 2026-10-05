# Copyright (c) 2026 PitchAI. All rights reserved.
"""Retained expected down dashboard fixture values."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .monitor_dashboard_fixture import fixture_config, fixture_snapshot

if TYPE_CHECKING:
    from e2e_registry.dashboard_data import MonitorData


def make_expected_down_fixture(now: float) -> MonitorData:
    """Build the unchanged expected down observation fixture.

    Returns:
        The original synthetic observations and any external test status.
    """
    domains = ["agentcloud.pitchai.net", "pitchai.net"]
    return fixture_snapshot(
        state={
            "updated_at": now,
            "history": {domain: [[now, False, 250.0, 400.0, 502]] for domain in domains},
            "last_ok": dict.fromkeys(domains, False),
            "fail_streak": dict.fromkeys(domains, 3),
            "success_streak": dict.fromkeys(domains, 0),
        },
        config=fixture_config(
            groups={
                "core": {"label": "PitchAI core", "description": "Critical production", "order": 10},
                "infrastructure": {"label": "Infrastructure", "description": "Internal services", "order": 20},
            },
            domains=[
                {
                    "domain": "agentcloud.pitchai.net",
                    "label": "AgentCloud",
                    "group": "infrastructure",
                    "environment": "internal",
                    "kind": "application",
                    "sources": ["test fixture"],
                    "alert_policy": {"telegram": "dashboard-only", "reason": "Not actively used right now."},
                },
                {
                    "domain": "pitchai.net",
                    "label": "PitchAI website",
                    "group": "core",
                    "environment": "production",
                    "kind": "application",
                    "sources": ["test fixture"],
                },
            ],
            reviewed_at="2026-08-25",
        ),
        now=now,
    )
