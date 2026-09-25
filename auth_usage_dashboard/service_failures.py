# Copyright (c) 2026 PitchAI. All rights reserved.
"""Contain declared source failures while preserving the last good snapshot."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, NamedTuple

from .capacity import build_dashboard_snapshot, isoformat

if TYPE_CHECKING:
    from datetime import datetime

    from .models import DashboardSnapshot, DashboardWarning
    from .settings import DashboardSettings


class SourceFailureInputs(NamedTuple):
    """Bundle source-failure context for degraded snapshot construction."""

    settings: DashboardSettings
    now: datetime
    error_name: str
    last_safe_probe_at: datetime | None
    last_analytics_probe_at: datetime | None


def source_failure_snapshot(
    existing: DashboardSnapshot | None,
    inputs: SourceFailureInputs,
) -> DashboardSnapshot:
    """Create or update a snapshot after a declared source boundary failure.

    Returns:
        The resulting value.

    """
    if existing is None:
        return _initial_failure_snapshot(inputs)
    snapshot = copy.deepcopy(existing)
    snapshot["generated_at"] = isoformat(inputs.now)
    snapshot["source"]["stale"] = True
    snapshot["source"]["error"] = inputs.error_name
    source_warning: DashboardWarning = {
        "severity": "critical",
        "code": "source_error",
        "message": "Broker state refresh failed",
    }
    retained_warnings: list[DashboardWarning] = [
        item for item in snapshot["warnings"] if item["code"] != "source_error"
    ]
    snapshot["warnings"] = [source_warning, *retained_warnings]
    return snapshot


def _initial_failure_snapshot(inputs: SourceFailureInputs) -> DashboardSnapshot:
    settings = inputs.settings
    return build_dashboard_snapshot(
        [],
        now=inputs.now,
        stale_after_seconds=settings.stale_after_seconds,
        analytics_stale_after_seconds=settings.analytics_stale_after_seconds,
        min_five_hour_remaining_percent=settings.min_five_hour_remaining_percent,
        source_error=inputs.error_name,
        last_safe_probe_at=inputs.last_safe_probe_at,
        last_analytics_probe_at=inputs.last_analytics_probe_at,
        probe_interval_seconds=settings.safe_probe_interval_seconds,
        analytics_probe_interval_seconds=settings.analytics_probe_interval_seconds,
    )
