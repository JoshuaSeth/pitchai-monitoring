# Copyright (c) 2026 PitchAI. All rights reserved.
"""Load the compact database dependency state into a dashboard contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

from monitoring_contracts.json_types import (
    bool_value,
    float_value,
    int_value,
    json_object,
    object_list,
    optional_object,
    text_value,
    value_list,
)
from monitoring_database_dependencies.sanitization import sanitized_excerpt

if TYPE_CHECKING:
    from monitoring_contracts.json_types import JsonObject, JsonValue

_DEFAULT_STATE_PATH = "/monitor_state/database-dependencies.json"
_MAX_STATE_BYTES = 4_194_304
_VALID_STATUSES = {"healthy", "degraded", "down"}
_VALID_VERSIONS = {1, 2}


class DatabaseDashboardStateError(RuntimeError):
    """The database collector state cannot be represented truthfully."""


def _clean_text(value: JsonValue | object) -> str | None:
    cleaned = sanitized_excerpt(value)
    return cleaned or None


def _text_array(value: JsonValue | object) -> list[JsonValue]:
    return [item for item in value_list(value) if isinstance(item, str) and item]


def _dependency(raw: JsonObject) -> JsonObject:
    dependency_id = text_value(raw.get("dependency_id"))
    if not dependency_id:
        message = "database dependency id is missing"
        raise DatabaseDashboardStateError(message)
    status = text_value(raw.get("status"), default="unknown")
    if status not in _VALID_STATUSES:
        message = "database dependency status is invalid"
        raise DatabaseDashboardStateError(message)
    return {
        "dependency_id": dependency_id,
        "dependency_kind": text_value(raw.get("dependency_kind"), default="database"),
        "status": status,
        "affected_app": _clean_text(raw.get("affected_app")),
        "container": _clean_text(raw.get("container")),
        "database_dependency": _clean_text(raw.get("database_dependency")),
        "owner_project": _clean_text(raw.get("owner_project")),
        "environment": text_value(raw.get("environment"), default="unspecified"),
        "critical": bool_value(raw.get("critical")) is True,
        "telegram_policy_enabled": bool_value(raw.get("telegram_policy_enabled")) is True,
        "telegram_route_eligible": bool_value(raw.get("telegram_route_eligible")) is True,
        "telegram_alert_enabled": bool_value(raw.get("telegram_alert_enabled")) is True,
        "telegram_alert_eligible": bool_value(raw.get("telegram_alert_eligible")) is True,
        "telegram_suppression_reason": _clean_text(raw.get("telegram_suppression_reason")),
        "observed_at_ts": float_value(raw.get("observed_at_ts")),
        "last_success_at_ts": float_value(raw.get("last_success_at_ts")),
        "last_success_latency_ms": float_value(raw.get("last_success_latency_ms")),
        "last_failure_at_ts": float_value(raw.get("last_failure_at_ts")),
        "last_failure_latency_ms": float_value(raw.get("last_failure_latency_ms")),
        "failure_started_at_ts": float_value(raw.get("failure_started_at_ts")),
        "latency_ms": float_value(raw.get("latency_ms")),
        "failure_class": _clean_text(raw.get("failure_class")),
        "last_failure_class": _clean_text(raw.get("last_failure_class")),
        "failure_phase": _clean_text(raw.get("failure_phase")),
        "sqlstate": _clean_text(raw.get("sqlstate")),
        "credential_state": _clean_text(raw.get("credential_state")),
        "credential_source": _clean_text(raw.get("credential_source")),
        "sanitized_error_excerpt": _clean_text(raw.get("sanitized_error_excerpt")),
        "last_failure_excerpt": _clean_text(raw.get("last_failure_excerpt")),
        "failure_streak": int_value(raw.get("failure_streak")) or 0,
        "success_streak": int_value(raw.get("success_streak")) or 0,
        "likely_fix_path": _clean_text(raw.get("likely_fix_path")),
        "domains": _text_array(raw.get("domains")),
        "coverage": _text_array(raw.get("coverage")),
        "routing_policy_id": _clean_text(raw.get("routing_policy_id")),
        "traffic_slot": _clean_text(raw.get("traffic_slot")),
        "traffic_state": _clean_text(raw.get("traffic_state")),
        "traffic_weight": int_value(raw.get("traffic_weight")),
        "routing_source": _clean_text(raw.get("routing_source")),
        "routing_error": _clean_text(raw.get("routing_error")),
        "alert_group": _clean_text(raw.get("alert_group")),
    }


def _empty_contract(path: Path, *, data_state: str, error_class: str | None = None) -> JsonObject:
    return {
        "status": "degraded" if data_state != "missing" else "unknown",
        "data_state": data_state,
        "generated_at_ts": None,
        "age_seconds": None,
        "state_path": path.name,
        "collector_status": "degraded" if data_state != "missing" else "unknown",
        "collector_error_class": error_class,
        "collector_observed_at_ts": None,
        "total": 0,
        "healthy": 0,
        "degraded": 0,
        "down": 0,
        "critical_down": 0,
        "alertable_down": 0,
        "standby_degraded": 0,
        "open_alert_groups": 0,
        "items": [],
    }


def _read_state(path: Path) -> JsonObject:
    with path.open("rb") as stream:
        payload = stream.read(_MAX_STATE_BYTES + 1)
    if len(payload) > _MAX_STATE_BYTES:
        message = "database state exceeds its bounded size"
        raise DatabaseDashboardStateError(message)
    decoded = cast("JsonValue", json.loads(payload.decode("utf-8")))
    state = json_object(decoded)
    if int_value(state.get("version")) not in _VALID_VERSIONS:
        message = "database state version is unsupported"
        raise DatabaseDashboardStateError(message)
    return state


def _validated_dependencies(state: JsonObject) -> list[JsonObject]:
    raw_items = object_list(state.get("dependencies"))
    items = [_dependency(item) for item in raw_items]
    identifiers = [text_value(item.get("dependency_id")) for item in items]
    if len(identifiers) != len(set(identifiers)):
        message = "database dependency ids are duplicated"
        raise DatabaseDashboardStateError(message)
    return items


def _collector_projection(state: JsonObject, *, now_ts: float) -> JsonObject:
    generated_at = float_value(state.get("generated_at_ts"))
    collector = optional_object(state.get("collector"))
    interval = int_value(collector.get("interval_seconds"))
    collector_status = text_value(collector.get("status"), default="degraded")
    age = None if generated_at is None else max(0.0, now_ts - generated_at)
    stale = generated_at is None or interval is None or age is None or age > interval * 2.5
    data_state = "stale" if stale else "degraded" if collector_status != "healthy" else "live"
    source_status = text_value(state.get("status"), default="degraded")
    if source_status not in _VALID_STATUSES:
        source_status = "degraded"
    dashboard_status = source_status
    if data_state != "live":
        dashboard_status = "down" if source_status == "down" else "degraded"
    return json_object({
        "status": dashboard_status,
        "data_state": data_state,
        "generated_at_ts": generated_at,
        "age_seconds": age,
        "collector_status": collector_status,
        "collector_error_class": _clean_text(collector.get("error_class")),
        "collector_observed_at_ts": float_value(collector.get("observed_at_ts")),
    })


def _dependency_counts(items: list[JsonObject], state: JsonObject) -> JsonObject:
    statuses = [text_value(item.get("status")) for item in items]
    alertable_down = 0
    standby_degraded = 0
    for item in items:
        if bool_value(item.get("telegram_alert_eligible")) is True:
            alertable_down += 1
        if text_value(item.get("traffic_state")) == "inactive" and text_value(item.get("status")) == "degraded":
            standby_degraded += 1
    open_alert_groups = sum(
        text_value(group.get("status")) == "down" for group in object_list(state.get("alert_groups"))
    )
    return json_object({
        "total": len(items),
        "healthy": statuses.count("healthy"),
        "degraded": statuses.count("degraded"),
        "down": statuses.count("down"),
        "critical_down": alertable_down,
        "alertable_down": alertable_down,
        "standby_degraded": standby_degraded,
        "open_alert_groups": open_alert_groups,
    })


def load_database_dashboard(*, now_ts: float) -> JsonObject:
    """Return sanitized DB dependency data or an explicit collector failure.

    Returns:
        The current database dashboard contract or a truthful collector failure.
    """
    configured_path = os.getenv("DATABASE_DEPENDENCY_STATE_PATH", _DEFAULT_STATE_PATH)
    path = Path(configured_path)
    if not path.exists():
        return _empty_contract(path, data_state="missing")
    state = _read_state(path)
    items = _validated_dependencies(state)
    collector = _collector_projection(state, now_ts=now_ts)
    counts = _dependency_counts(items, state)
    return json_object({
        "status": collector.get("status"),
        "data_state": collector.get("data_state"),
        "generated_at_ts": collector.get("generated_at_ts"),
        "age_seconds": collector.get("age_seconds"),
        "state_path": path.name,
        "collector_status": collector.get("collector_status"),
        "collector_error_class": collector.get("collector_error_class"),
        "collector_observed_at_ts": collector.get("collector_observed_at_ts"),
        "total": counts.get("total"),
        "healthy": counts.get("healthy"),
        "degraded": counts.get("degraded"),
        "down": counts.get("down"),
        "critical_down": counts.get("critical_down"),
        "alertable_down": counts.get("alertable_down"),
        "standby_degraded": counts.get("standby_degraded"),
        "open_alert_groups": counts.get("open_alert_groups"),
        "items": items,
    })
