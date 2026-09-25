# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared monitor-data construction for dashboard aggregation tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from e2e_registry.monitor_types import MonitorData

if TYPE_CHECKING:
    from e2e_registry.monitor_types import MonitorRecord, MonitorValue


def build_monitor_data(
    *,
    now: float,
    state: MonitorRecord,
    reviewed_at: str,
    groups: MonitorRecord,
    domains: list[MonitorValue],
) -> MonitorData:
    """Build deterministic dashboard source data around scenario-specific values.

    Returns:
        Loaded monitor data with stable test provenance and paths.
    """
    config: MonitorRecord = {
        "interval_seconds": 60,
        "inventory": {
            "version": 1,
            "reviewed_at": reviewed_at,
            "authoritative_sources": ["test fixture"],
        },
        "domain_groups": groups,
        "domains": domains,
        "retired_domains": [],
    }
    return MonitorData(
        state=state,
        config=config,
        state_path="/monitor/state.json",
        config_path="/monitor/config.yaml",
        loaded_at_ts=now,
        state_error=None,
    )
