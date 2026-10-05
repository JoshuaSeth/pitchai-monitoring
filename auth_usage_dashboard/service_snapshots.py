# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build the cached capacity snapshot, including its degraded form after a failed refresh."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, NamedTuple, cast

from .capacity import build_dashboard_snapshot, isoformat
from .timeseries_types import require_object

if TYPE_CHECKING:
    from datetime import datetime

    from .service_probes import ProbeLedger
    from .settings import DashboardSettings
    from .timeseries_types import JsonObject

_SOURCE_ERROR_WARNING_CODE = "source_error"


class RecordedHistory(NamedTuple):
    """Usage samples persisted during one refresh, or the name of the persistence failure."""

    samples: list[JsonObject] | None = None
    error: str | None = None


def current_snapshot(
    raw_accounts: list[JsonObject],
    *,
    settings: DashboardSettings,
    probes: ProbeLedger,
    now: datetime,
    history: RecordedHistory | None = None,
) -> JsonObject:
    """Project raw broker accounts, the latest probe results, and recorded history into one snapshot.

    Returns:
        The dashboard snapshot for ``now``.
    """
    recorded = RecordedHistory() if history is None else history
    return build_dashboard_snapshot(
        raw_accounts,
        now=now,
        stale_after_seconds=settings.stale_after_seconds,
        analytics_stale_after_seconds=settings.analytics_stale_after_seconds,
        min_five_hour_remaining_percent=settings.min_five_hour_remaining_percent,
        probe_errors=probes.last_probe_errors,
        analytics_probe_errors=probes.last_analytics_probe_errors,
        source_error=None,
        last_safe_probe_at=probes.last_safe_probe_at,
        last_analytics_probe_at=probes.last_analytics_probe_at,
        probe_interval_seconds=settings.safe_probe_interval_seconds,
        analytics_probe_interval_seconds=settings.analytics_probe_interval_seconds,
        usage_samples=recorded.samples,
        history_error=recorded.error,
    )


def failed_refresh_snapshot(
    previous: JsonObject | None,
    *,
    error_name: str,
    settings: DashboardSettings,
    probes: ProbeLedger,
    now: datetime,
) -> JsonObject:
    """Describe a failed broker refresh without discarding the last good capacity.

    Returns:
        An empty snapshot carrying the error before any success, otherwise the
        previous snapshot marked stale with a leading critical source warning.
    """
    if previous is None:
        return build_dashboard_snapshot(
            [],
            now=now,
            stale_after_seconds=settings.stale_after_seconds,
            analytics_stale_after_seconds=settings.analytics_stale_after_seconds,
            min_five_hour_remaining_percent=settings.min_five_hour_remaining_percent,
            source_error=error_name,
            last_safe_probe_at=probes.last_safe_probe_at,
            last_analytics_probe_at=probes.last_analytics_probe_at,
            probe_interval_seconds=settings.safe_probe_interval_seconds,
            analytics_probe_interval_seconds=settings.analytics_probe_interval_seconds,
        )
    snapshot = copy.deepcopy(previous)
    snapshot["generated_at"] = isoformat(now)
    source = require_object(snapshot["source"], description="capacity snapshot source")
    source["stale"] = True
    source["error"] = error_name
    earlier_warnings = cast("list[JsonObject]", cast("object", snapshot.get("warnings", [])))
    retained_warnings = [warning for warning in earlier_warnings if warning.get("code") != _SOURCE_ERROR_WARNING_CODE]
    source_warning: JsonObject = {
        "severity": "critical",
        "code": _SOURCE_ERROR_WARNING_CODE,
        "message": "Broker state refresh failed",
    }
    snapshot["warnings"] = [source_warning, *retained_warnings]
    return snapshot
