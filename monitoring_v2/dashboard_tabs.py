# Copyright (c) 2026 PitchAI. All rights reserved.
"""Deterministic retained-data fixture for actionable dashboard browser proof."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .database_incidents import build_database_incidents
from .json_types import optional_object

if TYPE_CHECKING:
    from .json_types import JsonObject


def build_actionable_dashboard_summary(summary: JsonObject, *, domain: str) -> JsonObject:
    """Enrich retained dashboard data with one domain and one DB incident.

    Returns:
        A complete summary contract enriched with deterministic failures.
    """
    now = time.time()
    database_item: JsonObject = {
        "dependency_id": "billing-web:runtime-postgres",
        "dependency_kind": "database",
        "status": "down",
        "affected_app": "Billing web",
        "container": "billing-web-green",
        "database_dependency": "Runtime PostgreSQL",
        "owner_project": "Billing",
        "environment": "production",
        "critical": True,
        "telegram_policy_enabled": True,
        "telegram_route_eligible": True,
        "telegram_alert_enabled": True,
        "telegram_alert_eligible": True,
        "telegram_suppression_reason": None,
        "observed_at_ts": now,
        "last_success_at_ts": now - 600,
        "last_success_latency_ms": 8.4,
        "last_failure_at_ts": now,
        "last_failure_latency_ms": 42.1,
        "failure_started_at_ts": now - 300,
        "latency_ms": 42.1,
        "failure_class": "invalid_or_revoked_password",
        "last_failure_class": "invalid_or_revoked_password",
        "failure_phase": "connection",
        "sqlstate": "28P01",
        "credential_state": "stale_or_revoked_after_last_success",
        "credential_source": "runtime_environment",
        "sanitized_error_excerpt": "password authentication failed for role <redacted>",
        "last_failure_excerpt": "password authentication failed for role <redacted>",
        "failure_streak": 3,
        "success_streak": 0,
        "likely_fix_path": "Rotate the production credential and restore the active PgBouncer route.",
        "domains": [domain],
        "coverage": [
            "login/authentication",
            "PgBouncer/tunnel connectivity",
            "schema usage grant",
            "configured table permission",
            "bounded query timeout",
        ],
        "routing_policy_id": "billing-blue-green",
        "traffic_slot": "green",
        "traffic_state": "active",
        "traffic_weight": 100,
        "routing_source": "nginx upstream",
        "routing_error": None,
        "alert_group": "billing-database",
    }
    databases: JsonObject = {
        "status": "down",
        "data_state": "live",
        "generated_at_ts": now,
        "age_seconds": 0.0,
        "state_path": "database-dependencies.json",
        "collector_status": "healthy",
        "collector_error_class": None,
        "collector_observed_at_ts": now,
        "total": 1,
        "healthy": 0,
        "degraded": 0,
        "down": 1,
        "critical_down": 1,
        "alertable_down": 1,
        "standby_degraded": 0,
        "open_alert_groups": 1,
        "items": [database_item],
    }
    domain_incident: JsonObject = {
        "incident_id": f"domain_down:{domain}",
        "kind": "domain_down",
        "severity": "critical",
        "title": f"{domain} is down",
        "detail": "PitchAI core · HTTP readiness is down.",
        "current_status": "down",
        "affected_check": "HTTP readiness",
        "affected_service": domain,
        "domain": domain,
        "environment": "production",
        "group": "core",
        "group_label": "PitchAI core",
        "owner_project": "PitchAI core",
        "status_code": 503,
        "error_message": "upstream unavailable",
        "response_excerpt": "service temporarily unavailable",
        "first_seen_at_ts": now - 300,
        "latest_seen_at_ts": now,
        "observed_at_ts": now,
        "last_successful_sample": {
            "observed_at_ts": now - 600,
            "status_code": 200,
            "latency_ms": 110.0,
        },
        "trend": {"direction": "degrading", "observations": 3, "points": []},
        "alert_policy": {"channel": "Telegram", "enabled": True, "mode": "critical"},
        "telegram_alert": True,
        "expected": False,
        "suggested_next_action": "Inspect the active deployment and proxy logs.",
        "evidence_state": "retained",
    }
    summary["incidents"] = [domain_incident, *build_database_incidents(databases)]
    dashboards = optional_object(summary.get("dashboards"))
    dashboards["databases"] = databases
    summary["dashboards"] = dashboards
    return summary
