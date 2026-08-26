# Copyright (c) 2026 PitchAI. All rights reserved.
"""Compose database dependency failures into actionable incidents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain_checks.monitoring_contracts.json_types import (
    bool_value,
    float_value,
    int_value,
    object_list,
    text_value,
)

if TYPE_CHECKING:
    from domain_checks.monitoring_contracts.json_types import JsonObject


def _collector_incident(databases: JsonObject) -> JsonObject | None:
    data_state = text_value(databases.get("data_state"), default="missing")
    if data_state == "live":
        return None
    titles = {
        "missing": "Database dependency state is unavailable",
        "stale": "Database dependency state is stale",
        "invalid": "Database dependency state is invalid",
        "unreadable": "Database dependency state is unreadable",
        "degraded": "Database dependency collector is degraded",
    }
    return {
        "incident_id": "database_dependency_collector",
        "kind": "database_dependency_collector",
        "severity": "warning",
        "title": titles.get(data_state, "Database dependency collector is degraded"),
        "detail": "The dedicated collector has not produced a trustworthy current database snapshot.",
        "current_status": data_state,
        "affected_check": text_value(
            databases.get("collector_error_class"),
            default="database dependency collector",
        ),
        "affected_service": "production database monitoring",
        "owner_project": "PitchAI monitoring",
        "latest_seen_at_ts": float_value(databases.get("collector_observed_at_ts"))
        or float_value(databases.get("generated_at_ts")),
        "alert_policy": {
            "channel": "Telegram",
            "enabled": False,
            "mode": "collector gap; dashboard only",
            "reason": "collector failures never infer a production database outage",
        },
        "suggested_next_action": (
            "Inspect the database-dependency-monitor sidecar, state volume, routing mount, and bounded Docker boundary."
        ),
        "tab_target": "databases",
        "evidence_state": data_state,
    }


def _dependency_incident(item: JsonObject) -> JsonObject:
    status = text_value(item.get("status"), default="unknown")
    alertable = bool_value(item.get("telegram_alert_eligible")) is True
    app_name = text_value(item.get("affected_app"), default="Unknown app")
    failure_class = text_value(item.get("failure_class"), default="database dependency failure")
    route_state = text_value(item.get("traffic_state"), default="unknown")
    detail = (
        f"The app's runtime database path failed its bounded read-only probe ({failure_class})."
        if text_value(item.get("dependency_kind"), default="database") == "database"
        else "A required production container group is absent, so database coverage is incomplete."
    )
    return {
        "incident_id": f"database_dependency:{text_value(item.get('dependency_id'))}",
        "kind": "database_dependency",
        "severity": "critical" if alertable else "warning",
        "title": f"{app_name} database dependency is {status}",
        "detail": detail,
        "current_status": status,
        "affected_check": failure_class,
        "affected_service": app_name,
        "affected_app": app_name,
        "container": item.get("container"),
        "database_dependency": item.get("database_dependency"),
        "owner_project": item.get("owner_project"),
        "environment": item.get("environment"),
        "dependency_id": item.get("dependency_id"),
        "first_seen_at_ts": float_value(item.get("failure_started_at_ts")),
        "latest_seen_at_ts": float_value(item.get("observed_at_ts")),
        "observed_at_ts": float_value(item.get("observed_at_ts")),
        "last_successful_sample": {
            "observed_at_ts": float_value(item.get("last_success_at_ts")),
            "latency_ms": float_value(item.get("last_success_latency_ms")),
        },
        "failure_class": item.get("failure_class"),
        "failure_phase": item.get("failure_phase"),
        "credential_state": item.get("credential_state"),
        "credential_source": item.get("credential_source"),
        "traffic_state": route_state,
        "traffic_slot": item.get("traffic_slot"),
        "traffic_weight": item.get("traffic_weight"),
        "routing_source": item.get("routing_source"),
        "routing_error": item.get("routing_error"),
        "alert_group": item.get("alert_group"),
        "error_message": item.get("sanitized_error_excerpt"),
        "failure_streak": int_value(item.get("failure_streak")) or 0,
        "trend": {
            "direction": "degrading" if status == "down" else "watching",
            "observations": int_value(item.get("failure_streak")) or 0,
            "points": [],
        },
        "alert_policy": {
            "channel": "Telegram",
            "enabled": alertable,
            "mode": "critical active-route production transition" if alertable else "dashboard only",
            "reason": item.get("telegram_suppression_reason"),
        },
        "telegram_alert": alertable,
        "suggested_next_action": item.get("likely_fix_path"),
        "tab_target": "databases",
        "evidence_state": "available",
    }


def build_database_incidents(databases: JsonObject) -> list[JsonObject]:
    """Return collector gaps plus every currently degraded/down dependency."""
    incidents: list[JsonObject] = []
    collector = _collector_incident(databases)
    if collector is not None:
        incidents.append(collector)
    incidents.extend(
        _dependency_incident(item)
        for item in object_list(databases.get("items"))
        if text_value(item.get("status")) in {"degraded", "down"}
    )
    return incidents
