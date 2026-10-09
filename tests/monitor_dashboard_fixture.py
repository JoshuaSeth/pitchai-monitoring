# Copyright (c) 2026 PitchAI. All rights reserved.
"""Common metadata for isolated dashboard observations."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from e2e_registry.dashboard_data import MonitorData

if TYPE_CHECKING:
    from domain_checks.config_values import ConfigValue
    from domain_checks.event_bus_delivery import JsonObject
    from e2e_registry.dashboard_records import Record


def fixture_config(*, groups: Record, domains: list[Record], reviewed_at: str) -> Record:
    """Build the original configuration metadata around explicit scenario values.

    Returns:
        A fresh configuration with the retained inventory and interval.
    """
    return {
        "interval_seconds": 60,
        "inventory": {"version": 1, "reviewed_at": reviewed_at, "authoritative_sources": ["test fixture"]},
        "domain_groups": groups,
        "domains": cast("list[ConfigValue]", domains),
        "retired_domains": [],
    }


def fixture_snapshot(*, state: JsonObject, config: Record, now: float) -> MonitorData:
    """Bind synthetic data to the existing display-only path metadata.

    Returns:
        The original immutable snapshot without accessing either path.
    """
    return MonitorData(
        state=state,
        config=config,
        state_path="/monitor/state.json",
        config_path="/monitor/config.yaml",
        loaded_at_ts=now,
        state_error=None,
    )
