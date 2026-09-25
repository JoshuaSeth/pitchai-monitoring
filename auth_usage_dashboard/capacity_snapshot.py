# Copyright (c) 2026 PitchAI. All rights reserved.
"""Assemble broker observations into one validated dashboard snapshot."""

from __future__ import annotations

from typing import TYPE_CHECKING, Unpack

from .capacity_account import parse_account
from .capacity_events import capacity_events
from .capacity_forecast import build_capacity_forecasts
from .capacity_payload import dashboard_payload
from .capacity_reset_bank import build_reset_bank
from .capacity_snapshot_types import (
    SnapshotOptions,
    SnapshotParts,
)
from .capacity_summary import snapshot_stats
from .capacity_warnings import build_warnings
from .history import build_hourly_usage_history
from .runout import build_runout_forecast, select_capacity_basis
from .value_parsing import account_lookup_key

if TYPE_CHECKING:
    from .capacity_snapshot_types import (
        SnapshotArguments,
    )
    from .json_contract import JsonObject
    from .models import CapacityAccount, DashboardSnapshot


def build_dashboard_snapshot(
    raw_accounts: list[JsonObject],
    **arguments: Unpack[SnapshotArguments],
) -> DashboardSnapshot:
    """Build a complete read-only dashboard snapshot.

    Returns:
        The resulting value.

    """
    options = _snapshot_options(arguments)
    accounts = _parse_accounts(raw_accounts, options=options)
    parts = _snapshot_parts(accounts, options=options)
    stats = snapshot_stats(accounts, parts.events)
    return dashboard_payload(accounts, options, parts, stats)


def _snapshot_options(arguments: SnapshotArguments) -> SnapshotOptions:
    return SnapshotOptions(
        arguments["now"],
        arguments["stale_after_seconds"],
        arguments["min_five_hour_remaining_percent"],
        arguments.get("analytics_stale_after_seconds", 1800),
        arguments.get("probe_errors") or {},
        arguments.get("analytics_probe_errors") or {},
        arguments.get("source_error"),
        arguments.get("last_safe_probe_at"),
        arguments.get("last_analytics_probe_at"),
        arguments.get("probe_interval_seconds", 300),
        arguments.get("analytics_probe_interval_seconds", 900),
        arguments.get("usage_samples") or [],
        arguments.get("history_error"),
    )


def _parse_accounts(
    raw_accounts: list[JsonObject],
    *,
    options: SnapshotOptions,
) -> list[CapacityAccount]:
    accounts: list[CapacityAccount] = []
    for raw in raw_accounts:
        lookup_key = account_lookup_key(raw)
        accounts.append(
            parse_account(
                raw,
                now=options.now,
                stale_after_seconds=options.stale_after_seconds,
                min_five_hour_remaining_percent=options.minimum_remaining,
                analytics_stale_after_seconds=options.analytics_stale_after_seconds,
                probe_error=options.probe_errors.get(lookup_key),
                analytics_probe_error=options.analytics_probe_errors.get(lookup_key),
            ),
        )
    accounts.sort(
        key=lambda account: (not account["enabled"], account["email"].lower()),
    )
    return accounts


def _snapshot_parts(
    accounts: list[CapacityAccount],
    *,
    options: SnapshotOptions,
) -> SnapshotParts:
    capacity_basis = select_capacity_basis(accounts)
    reset_bank = build_reset_bank(accounts, now=options.now)
    return SnapshotParts(
        capacity_basis,
        build_capacity_forecasts(
            accounts,
            now=options.now,
            window_key=capacity_basis.get("key"),
        ),
        build_hourly_usage_history(
            accounts,
            samples=options.usage_samples,
            now=options.now,
        ),
        reset_bank,
        build_runout_forecast(
            accounts,
            samples=options.usage_samples,
            reset_bank=reset_bank,
            now=options.now,
            capacity_basis=capacity_basis,
        ),
        build_warnings(
            accounts,
            source_error=options.source_error,
            history_error=options.history_error,
            probe_errors=options.probe_errors,
            analytics_probe_errors=options.analytics_probe_errors,
        ),
        capacity_events(accounts, now=options.now),
    )
