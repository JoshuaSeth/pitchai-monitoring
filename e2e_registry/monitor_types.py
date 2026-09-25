# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared data contracts for monitoring dashboard aggregation."""

from __future__ import annotations

from dataclasses import dataclass

type MonitorScalar = str | int | float | bool | None
type MonitorSample = tuple[float, bool, float | None, float | None, int | None]
type MonitorValue = MonitorScalar | list[MonitorValue] | dict[str, MonitorValue] | MonitorSample
type MonitorRecord = dict[str, MonitorValue]
type MonitorRecords = list[MonitorRecord]


@dataclass(frozen=True)
class MonitorData:
    """Loaded monitor state, inventory, provenance, and validation status."""

    state: MonitorRecord
    config: MonitorRecord
    state_path: str
    config_path: str
    loaded_at_ts: float
    state_error: str | None
