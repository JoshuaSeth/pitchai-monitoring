# Copyright (c) 2026 PitchAI. All rights reserved.
"""Selected-range filtering for dashboard event and dispatch responses."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from domain_checks.cycle_values import required_float

from .dashboard_records import array_or_empty, object_or_empty

if TYPE_CHECKING:
    from domain_checks.config_values import ConfigValue

    from .dashboard_records import Record


def _selected_rows(
    value: ConfigValue, since_ts: float, until_ts: float, *, keep_undated: bool,
) -> list[ConfigValue]:
    selected: list[ConfigValue] = []
    for row in array_or_empty(value):
        if not isinstance(row, dict):
            continue
        timestamp: float | None = None
        # The response historically omits invalid event timestamps but retains
        # undated dispatches. This filtering does not alter incident state.
        with suppress(Exception):
            timestamp = required_float(row.get("ts") or 0.0)
        if timestamp is None:
            if not keep_undated:
                continue
            timestamp = 0.0
        if keep_undated and not timestamp:
            selected.append(row)
            continue
        if timestamp < float(since_ts) or timestamp > float(until_ts):
            continue
        selected.append(row)
    return selected


def filter_summary_window(summary: Record, *, since_ts: float, until_ts: float) -> None:
    """Retain response mutation, row identity and distinct undated-row policies."""
    summary["events"] = _selected_rows(summary.get("events"), since_ts, until_ts, keep_undated=False)
    dispatch = object_or_empty(summary.get("dispatch"))
    dispatch["recent"] = _selected_rows(dispatch.get("recent"), since_ts, until_ts, keep_undated=True)
    summary["dispatch"] = dispatch
