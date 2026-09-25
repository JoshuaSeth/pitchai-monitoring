# Copyright (c) 2026 PitchAI. All rights reserved.
"""Serialize normalized snapshot parts into the public dashboard contract."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .capacity_events import CAPACITY_EVENT_HORIZON_SECONDS
from .value_parsing import isoformat, optional_isoformat

if TYPE_CHECKING:
    from .capacity_snapshot_types import SnapshotOptions, SnapshotParts, SnapshotStats
    from .models import (
        CapacityAccount,
        DashboardMethodology,
        DashboardSnapshot,
        DashboardSource,
        DashboardSummary,
    )


def dashboard_payload(
    accounts: list[CapacityAccount],
    options: SnapshotOptions,
    parts: SnapshotParts,
    stats: SnapshotStats,
) -> DashboardSnapshot:
    """Build the complete schema-versioned public snapshot.

    Returns:
        The resulting value.

    """
    return {
        "schema_version": 4,
        "generated_at": isoformat(options.now),
        "source": _source_payload(options, stats),
        "summary": _summary_payload(accounts, parts, stats),
        "forecasts": parts.forecasts,
        "runout_forecast": parts.runout_forecast,
        "usage_history": parts.usage_history,
        "reset_bank": parts.reset_bank,
        "warnings": parts.warnings,
        "events": parts.events,
        "accounts": accounts,
        "methodology": _methodology(),
    }


def _source_payload(
    options: SnapshotOptions,
    stats: SnapshotStats,
) -> DashboardSource:
    return {
        "name": "authoritative Codex authentication broker",
        "mode": "read-only state files plus no-generation usage and analytics probes",
        "probe_interval_seconds": options.probe_interval_seconds,
        "analytics_probe_interval_seconds": options.analytics_probe_interval_seconds,
        "last_safe_probe_at": optional_isoformat(options.last_safe_probe_at),
        "last_analytics_probe_at": optional_isoformat(
            options.last_analytics_probe_at,
        ),
        "oldest_account_probe_at": optional_isoformat(stats.oldest_probe),
        "newest_account_probe_at": optional_isoformat(stats.newest_probe),
        "stale": bool(
            options.source_error or stats.stale_count or stats.analytics_stale_count,
        ),
        "stale_account_count": stats.stale_count,
        "analytics_stale_account_count": stats.analytics_stale_count,
        "history_error": options.history_error,
        "error": options.source_error,
    }


def _summary_payload(
    accounts: list[CapacityAccount],
    parts: SnapshotParts,
    stats: SnapshotStats,
) -> DashboardSummary:
    next_useful = stats.next_useful
    return {
        "configured_accounts": len(accounts),
        "enabled_accounts": len(stats.enabled_accounts),
        "usable_now": stats.fresh_usable_count,
        "status_counts": stats.status_counts,
        "window_aggregates": stats.window_aggregates,
        "capacity_basis": parts.capacity_basis,
        "next_useful_capacity_at": next_useful["at"] if next_useful else None,
        "next_useful_capacity_label": (next_useful["account_label"] if next_useful else None),
        "capacity_event_horizon_seconds": CAPACITY_EVENT_HORIZON_SECONDS,
    }


def _methodology() -> DashboardMethodology:
    return {
        "unit": "normalized reported-window capacity point",
        "definition": (
            "100 points equals one full account window for the declared forecast "
            "basis. The dashboard prefers measured five-hour windows and otherwise "
            "uses measured weekly windows."
        ),
        "weekly_handling": (
            "Weekly exhaustion blocks selection until its provider-reported reset. "
            "When weekly is the forecast basis, its remaining percentage is used "
            "directly rather than relabeled as five-hour capacity."
        ),
        "missing_windows": (
            "A provider window that is not reported remains unavailable and is never "
            "converted to zero usage or zero remaining capacity."
        ),
        "maximum_not_prediction": True,
        "token_history": (
            "Provider daily totals are reconstructed into 168 hourly UTC points and "
            "progressively replaced by native sample deltas; the current hour is "
            "partial."
        ),
        "runout_forecast": (
            "Probabilities model recent percentage-point burn and automatic resets "
            "for the declared provider-window basis. Banked resets are excluded "
            "because redemption is manual and forbidden here."
        ),
        "reset_bank": ("Read-only inventory. The dashboard has no action that can consume a banked reset."),
    }
