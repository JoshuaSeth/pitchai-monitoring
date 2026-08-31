# Copyright (c) 2026 PitchAI. All rights reserved.
"""Secret-free capacity projection shared by the iPhone and Watch clients."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue

_WINDOW_FIELDS = (
    "reported",
    "used_percent",
    "remaining_percent",
    "reset_at",
    "reset_in_seconds",
    "window_seconds",
)
_AGGREGATE_FIELDS = (
    "measurement_status",
    "reporting_accounts",
    "unknown_accounts",
    "remaining_points",
    "maximum_known_points",
    "remaining_percent",
)
_STATUS_KEYS = (
    "available",
    "five_hour_limited",
    "weekly_limited",
    "auth_invalid",
    "disabled",
    "unknown",
)


def build_mobile_snapshot(
    snapshot: JsonObject,
    *,
    manual_refresh_min_interval_seconds: int,
    recommended_background_refresh_seconds: int,
) -> JsonObject:
    """Return the deliberately small, secret-free native client contract."""
    refresh_policy: JsonObject = {
        "manual_min_interval_seconds": manual_refresh_min_interval_seconds,
        "recommended_background_interval_seconds": recommended_background_refresh_seconds,
    }
    return {
        "schema_version": 1,
        "generated_at": snapshot.get("generated_at"),
        "source": _project_source(snapshot.get("source")),
        "summary": _project_summary(snapshot.get("summary")),
        "warnings": _project_warnings(snapshot.get("warnings")),
        "accounts": _project_accounts(snapshot.get("accounts")),
        "refresh_policy": refresh_policy,
    }


def _project_source(raw: JsonValue) -> JsonObject:
    source = _mapping(raw)
    return {
        "stale": bool(source.get("stale")),
        "stale_account_count": _integer(source.get("stale_account_count")),
        "newest_account_probe_at": source.get("newest_account_probe_at"),
        "last_safe_probe_at": source.get("last_safe_probe_at"),
        "error": source.get("error"),
    }


def _project_summary(raw: JsonValue) -> JsonObject:
    summary = _mapping(raw)
    aggregates = _mapping(summary.get("window_aggregates"))
    windows: JsonObject = {}
    for key in ("five_hour", "weekly"):
        windows[key] = _pick(_mapping(aggregates.get(key)), _AGGREGATE_FIELDS)
    return {
        "configured_accounts": _integer(summary.get("configured_accounts")),
        "enabled_accounts": _integer(summary.get("enabled_accounts")),
        "usable_now": _integer(summary.get("usable_now")),
        "status_counts": _status_counts(summary.get("status_counts")),
        "capacity_basis": _project_capacity_basis(summary.get("capacity_basis")),
        "window_aggregates": windows,
        "next_useful_capacity_at": summary.get("next_useful_capacity_at"),
        "next_useful_capacity_label": summary.get("next_useful_capacity_label"),
    }


def _project_capacity_basis(raw: JsonValue) -> JsonObject:
    basis = _mapping(raw)
    return {
        "key": basis.get("key"),
        "label": basis.get("label"),
        "reporting_accounts": _integer(basis.get("reporting_accounts")),
        "eligible_accounts": _integer(basis.get("eligible_accounts")),
        "measurement_status": basis.get("measurement_status"),
    }


def _project_warnings(raw: JsonValue) -> list[JsonValue]:
    warnings = _array(raw)
    projected = (_mobile_warning(item) for item in warnings)
    return list(projected)


def _project_accounts(raw: JsonValue) -> list[JsonValue]:
    accounts = _array(raw)
    projected = (_mobile_account(item) for item in accounts)
    return list(projected)


def _mobile_account(raw: JsonValue) -> JsonObject:
    account = _mapping(raw)
    return {
        "label": account.get("label"),
        "enabled": bool(account.get("enabled")),
        "routing_preferred": bool(account.get("routing_preferred")),
        "plan_type": account.get("plan_type"),
        "status": account.get("status"),
        "status_reason": account.get("status_reason"),
        "auth_valid": account.get("auth_valid"),
        "selectable_now": bool(account.get("selectable_now")),
        "safety_floor_active": bool(account.get("safety_floor_active")),
        "five_hour": _pick(_mapping(account.get("five_hour")), _WINDOW_FIELDS),
        "weekly": _pick(_mapping(account.get("weekly")), _WINDOW_FIELDS),
        "last_probe_at": account.get("last_probe_at"),
        "stale": bool(account.get("stale")),
        "stale_seconds": account.get("stale_seconds"),
        "probe_error": account.get("probe_error"),
    }


def _mobile_warning(raw: JsonValue) -> JsonObject:
    warning = _mapping(raw)
    return {
        "severity": warning.get("severity"),
        "code": warning.get("code"),
        "account_label": warning.get("account_label"),
        "message": warning.get("message"),
    }


def _status_counts(raw: JsonValue) -> JsonObject:
    counts = _mapping(raw)
    projected: JsonObject = {}
    for key in _STATUS_KEYS:
        projected[key] = _integer(counts.get(key))
    return projected


def _pick(payload: JsonObject, fields: tuple[str, ...]) -> JsonObject:
    projected: JsonObject = {}
    for field in fields:
        projected[field] = payload.get(field)
    return projected


def _mapping(value: JsonValue) -> JsonObject:
    return value if isinstance(value, dict) else {}


def _array(value: JsonValue) -> list[JsonValue]:
    return value if isinstance(value, list) else []


def _integer(value: JsonValue) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
