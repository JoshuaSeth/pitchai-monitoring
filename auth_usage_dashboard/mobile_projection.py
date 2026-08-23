from __future__ import annotations

from typing import Any


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


def build_mobile_snapshot(
    snapshot: dict[str, Any],
    *,
    manual_refresh_min_interval_seconds: int,
    recommended_background_refresh_seconds: int,
) -> dict[str, Any]:
    """Return the deliberately small, secret-free native client contract."""

    source = _mapping(snapshot.get("source"))
    summary = _mapping(snapshot.get("summary"))
    aggregates = _mapping(summary.get("window_aggregates"))
    basis = _mapping(summary.get("capacity_basis"))

    return {
        "schema_version": 1,
        "generated_at": snapshot.get("generated_at"),
        "source": {
            "stale": bool(source.get("stale")),
            "stale_account_count": _integer(source.get("stale_account_count")),
            "newest_account_probe_at": source.get("newest_account_probe_at"),
            "last_safe_probe_at": source.get("last_safe_probe_at"),
            "error": source.get("error"),
        },
        "summary": {
            "configured_accounts": _integer(summary.get("configured_accounts")),
            "enabled_accounts": _integer(summary.get("enabled_accounts")),
            "usable_now": _integer(summary.get("usable_now")),
            "status_counts": _status_counts(summary.get("status_counts")),
            "capacity_basis": {
                "key": basis.get("key"),
                "label": basis.get("label"),
                "reporting_accounts": _integer(basis.get("reporting_accounts")),
                "eligible_accounts": _integer(basis.get("eligible_accounts")),
                "measurement_status": basis.get("measurement_status"),
            },
            "window_aggregates": {
                key: _pick(_mapping(aggregates.get(key)), _AGGREGATE_FIELDS)
                for key in ("five_hour", "weekly")
            },
            "next_useful_capacity_at": summary.get("next_useful_capacity_at"),
            "next_useful_capacity_label": summary.get(
                "next_useful_capacity_label"
            ),
        },
        "warnings": [_mobile_warning(item) for item in _list(snapshot.get("warnings"))],
        "accounts": [_mobile_account(item) for item in _list(snapshot.get("accounts"))],
        "refresh_policy": {
            "manual_min_interval_seconds": manual_refresh_min_interval_seconds,
            "recommended_background_interval_seconds": recommended_background_refresh_seconds,
        },
    }


def _mobile_account(raw: Any) -> dict[str, Any]:
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


def _mobile_warning(raw: Any) -> dict[str, Any]:
    warning = _mapping(raw)
    return {
        "severity": warning.get("severity"),
        "code": warning.get("code"),
        "account_label": warning.get("account_label"),
        "message": warning.get("message"),
    }


def _status_counts(raw: Any) -> dict[str, int]:
    counts = _mapping(raw)
    return {
        key: _integer(counts.get(key))
        for key in (
            "available",
            "five_hour_limited",
            "weekly_limited",
            "auth_invalid",
            "disabled",
            "unknown",
        )
    }


def _pick(payload: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: payload.get(field) for field in fields}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _integer(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
