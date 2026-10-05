# Copyright (c) 2026 PitchAI. All rights reserved.
"""Read-only Codex capacity dashboard snapshot assembled from broker state files."""

from __future__ import annotations

from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Required, TypedDict

from .capacity_account import parse_account
from .capacity_events import capacity_events, reset_bank
from .capacity_forecast import FORECAST_HORIZONS, build_forecasts
from .capacity_values import isoformat, parse_timestamp
from .capacity_warnings import build_warnings
from .capacity_windows import window_aggregate
from .history import build_hourly_usage_history
from .runout import build_runout_forecast, select_capacity_basis
from .timeseries_types import optional_object, require_object

if TYPE_CHECKING:
    from typing import Unpack

    from .timeseries_types import JsonObject

__all__ = [
    "CAPACITY_EVENT_HORIZON_SECONDS",
    "FORECAST_HORIZONS",
    "UTC",
    "SnapshotOptions",
    "build_dashboard_snapshot",
    "isoformat",
    "parse_account",
    "utc_now",
]

CAPACITY_EVENT_HORIZON_SECONDS = 8 * 24 * 60 * 60
_SCHEMA_VERSION = 4
_DEFAULT_ANALYTICS_STALE_AFTER_SECONDS = 1800
_DEFAULT_PROBE_INTERVAL_SECONDS = 300
_DEFAULT_ANALYTICS_PROBE_INTERVAL_SECONDS = 900
_STATUSES = ("available", "five_hour_limited", "weekly_limited", "auth_invalid", "disabled", "unknown")

utc_now = partial(datetime.now, UTC)


class SnapshotOptions(TypedDict, total=False):
    """Keyword options accepted by :func:`build_dashboard_snapshot`."""

    now: Required[datetime]
    stale_after_seconds: Required[int]
    min_five_hour_remaining_percent: Required[float]
    analytics_stale_after_seconds: int
    probe_errors: dict[str, str] | None
    analytics_probe_errors: dict[str, str] | None
    source_error: str | None
    last_safe_probe_at: datetime | None
    last_analytics_probe_at: datetime | None
    probe_interval_seconds: int
    analytics_probe_interval_seconds: int
    usage_samples: list[JsonObject] | None
    history_error: str | None


def build_dashboard_snapshot(raw_accounts: list[JsonObject], **options: Unpack[SnapshotOptions]) -> JsonObject:
    """Assemble the read-only capacity dashboard snapshot from raw broker accounts.

    Returns:
        Source freshness, fleet summary, forecasts, usage history, reset bank,
        warnings, reset events, normalized accounts, and the methodology notes.
    """
    now = options["now"]
    probe_errors = options.get("probe_errors") or {}
    analytics_probe_errors = options.get("analytics_probe_errors") or {}
    accounts = _parsed_accounts(raw_accounts, options, probe_errors, analytics_probe_errors)
    capacity_basis: JsonObject = select_capacity_basis(accounts)
    basis_key = capacity_basis.get("key")
    forecasts = build_forecasts(accounts, now=now, window_key=basis_key if isinstance(basis_key, str) else None)
    usage_history: JsonObject = build_hourly_usage_history(
        accounts,
        samples=options.get("usage_samples") or [],
        now=now,
    )
    bank = reset_bank(accounts, now=now)
    runout_forecast: JsonObject = build_runout_forecast(
        accounts,
        samples=options.get("usage_samples") or [],
        reset_bank=bank,
        now=now,
        capacity_basis=capacity_basis,
    )
    warnings = build_warnings(
        accounts,
        source_error=options.get("source_error"),
        history_error=options.get("history_error"),
        probe_errors=probe_errors,
        analytics_probe_errors=analytics_probe_errors,
    )
    events = capacity_events(accounts, now=now, horizon_seconds=CAPACITY_EVENT_HORIZON_SECONDS)
    return {
        "schema_version": _SCHEMA_VERSION,
        "generated_at": isoformat(now),
        "source": _source(accounts, options),
        "summary": _summary(accounts, capacity_basis=capacity_basis, events=events),
        "forecasts": forecasts,
        "runout_forecast": runout_forecast,
        "usage_history": usage_history,
        "reset_bank": bank,
        "warnings": warnings,
        "events": [*events],
        "accounts": [*accounts],
        "methodology": _methodology(),
    }


def _parsed_accounts(
    raw_accounts: list[JsonObject],
    options: SnapshotOptions,
    probe_errors: dict[str, str],
    analytics_probe_errors: dict[str, str],
) -> list[JsonObject]:
    accounts: list[JsonObject] = []
    for raw in raw_accounts:
        metadata = require_object(raw.get("metadata") or {}, description="broker account metadata")
        probe_key = str(metadata.get("label") or metadata.get("account_id") or "")
        account = parse_account(
            raw,
            now=options["now"],
            stale_after_seconds=options["stale_after_seconds"],
            analytics_stale_after_seconds=options.get(
                "analytics_stale_after_seconds",
                _DEFAULT_ANALYTICS_STALE_AFTER_SECONDS,
            ),
            min_five_hour_remaining_percent=options["min_five_hour_remaining_percent"],
            probe_error=probe_errors.get(probe_key),
            analytics_probe_error=analytics_probe_errors.get(probe_key),
        )
        accounts.append(dict(account))
    accounts.sort(key=lambda account: (not account["enabled"], str(account["email"]).lower()))
    return accounts


def _source(accounts: list[JsonObject], options: SnapshotOptions) -> JsonObject:
    probe_times: list[datetime] = []
    for account in accounts:
        probed_at = parse_timestamp(account.get("last_probe_at"))
        if probed_at is not None:
            probe_times.append(probed_at)
    enabled_accounts = [account for account in accounts if account["enabled"]]
    stale_count = sum(1 for account in enabled_accounts if account["stale"])
    analytics_stale_count = sum(
        1
        for account in enabled_accounts
        if optional_object(account["token_usage"])["stale"] or optional_object(account["reset_credits"])["stale"]
    )
    source_error = options.get("source_error")
    return {
        "name": "authoritative Codex authentication broker",
        "mode": "read-only state files plus no-generation usage and analytics probes",
        "probe_interval_seconds": options.get("probe_interval_seconds", _DEFAULT_PROBE_INTERVAL_SECONDS),
        "analytics_probe_interval_seconds": options.get(
            "analytics_probe_interval_seconds",
            _DEFAULT_ANALYTICS_PROBE_INTERVAL_SECONDS,
        ),
        "last_safe_probe_at": isoformat(options.get("last_safe_probe_at")),
        "last_analytics_probe_at": isoformat(options.get("last_analytics_probe_at")),
        "oldest_account_probe_at": isoformat(min(probe_times, default=None)),
        "newest_account_probe_at": isoformat(max(probe_times, default=None)),
        "stale": bool(source_error or stale_count or analytics_stale_count),
        "stale_account_count": stale_count,
        "analytics_stale_account_count": analytics_stale_count,
        "history_error": options.get("history_error"),
        "error": source_error,
    }


def _summary(accounts: list[JsonObject], *, capacity_basis: JsonObject, events: list[JsonObject]) -> JsonObject:
    enabled_accounts = [account for account in accounts if account["enabled"]]
    statuses = [account["status"] for account in accounts]
    status_counts: JsonObject = {status: statuses.count(status) for status in _STATUSES}
    restoring_events = (event for event in events if event["restores_selectability"])
    next_useful = next(restoring_events, next(iter(events), None))
    window_aggregates: JsonObject = {
        "five_hour": window_aggregate(enabled_accounts, key="five_hour"),
        "weekly": window_aggregate(enabled_accounts, key="weekly"),
    }
    return {
        "configured_accounts": len(accounts),
        "enabled_accounts": len(enabled_accounts),
        "usable_now": sum(1 for account in enabled_accounts if account["selectable_now"] and not account["stale"]),
        "status_counts": status_counts,
        "window_aggregates": window_aggregates,
        "capacity_basis": capacity_basis,
        "next_useful_capacity_at": next_useful["at"] if next_useful else None,
        "next_useful_capacity_label": next_useful["account_label"] if next_useful else None,
        "capacity_event_horizon_seconds": CAPACITY_EVENT_HORIZON_SECONDS,
    }


def _methodology() -> JsonObject:
    return {
        "unit": "normalized reported-window capacity point",
        "definition": (
            "100 points equals one full account window for the declared forecast basis. "
            "The dashboard prefers measured five-hour windows and otherwise uses measured weekly windows."
        ),
        "weekly_handling": (
            "Weekly exhaustion blocks selection unless the provider confirms spendable credits. "
            "When weekly is the forecast basis, its remaining percentage is used directly rather than relabeled "
            "as five-hour capacity."
        ),
        "missing_windows": (
            "A provider window that is not reported remains unavailable and is never converted to zero usage "
            "or zero remaining capacity."
        ),
        "maximum_not_prediction": True,
        "token_history": (
            "Provider daily totals are reconstructed into 168 hourly UTC points and progressively replaced by "
            "native sample deltas; the current hour is partial."
        ),
        "runout_forecast": (
            "Probabilities model recent percentage-point burn and automatic resets for the declared "
            "provider-window basis. Banked resets are excluded because redemption is manual and forbidden here."
        ),
        "usage_credits": (
            "Balances are provider credit units, not quota percentages or currency. Spendable credits extend "
            "usage but are excluded from percentage-based runout forecasts until credit burn is measured."
        ),
        "reset_bank": "Read-only inventory. The dashboard has no action that can consume a banked reset.",
    }
