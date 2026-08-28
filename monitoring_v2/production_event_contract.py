# Copyright (c) 2026 PitchAI. All rights reserved.
"""Actionable critical production-app events for the native Events Inbox."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, cast

from .domain_event_models import DomainTransitionEvent
from .incident_event_context import DOMAIN_CONFIG_PATH, MONITORING_SOURCE_URL, OUTGOING_MESSAGE_BOUNDARY
from .json_types import float_value, int_value, json_object, normalize_json
from .safe_evidence import safe_text_excerpt

if TYPE_CHECKING:
    from .domain_event_models import ProductionIncidentRoute
    from .json_types import JsonInput, JsonObject

_DASHBOARD_URL = "https://monitoring.pitchai.net/dashboard#incidents"


def production_failure_event(
    route: ProductionIncidentRoute,
    evidence: JsonObject,
    *,
    occurred_at: float,
    re_escalation: bool,
) -> DomainTransitionEvent:
    """Build one critical production-surface failure transition.

    Returns:
        Complete immutable transition for durable staging.
    """
    fingerprint = _failure_fingerprint(route, evidence=evidence)
    details = _common_details(route, fingerprint=fingerprint)
    detected_at = float_value(evidence.get("ts")) or occurred_at
    failed_checks = _failed_checks(route, evidence=evidence)
    details.update(
        {
            "severity": "critical",
            "detected_at_ts": detected_at,
            "detection_reason": failed_checks[0],
            "failed_checks": normalize_json(failed_checks),
            "evidence": normalize_json(_evidence_lines(route, evidence=evidence)),
            "repair_dispatch": "Immediately triage, repair, verify production, deploy if needed, and report privately.",
            "re_escalation": re_escalation,
            "incident_update": "persistent_failure_re_escalation" if re_escalation else "new_failure",
        },
    )
    _copy_numeric_evidence(details, evidence=evidence)
    return DomainTransitionEvent(kind="production_failure", occurred_at=occurred_at, details=details)


def production_recovered_event(
    route: ProductionIncidentRoute,
    *,
    incident_fingerprint: str,
    occurred_at: float,
) -> DomainTransitionEvent:
    """Build one recovery transition linked to an open production incident.

    Returns:
        Complete immutable recovery transition for durable staging.
    """
    details = _common_details(route, fingerprint=incident_fingerprint)
    details.update(
        {
            "severity": "info",
            "recovered_at_ts": occurred_at,
            "evidence": [f"{route.site}: debounced {route.signal} monitor recovered"],
            "repair_dispatch": "Verify live recovery and reconcile the existing incident lane.",
            "re_escalation": False,
            "incident_update": "recovered",
        },
    )
    return DomainTransitionEvent(kind="production_recovered", occurred_at=occurred_at, details=details)


def _common_details(route: ProductionIncidentRoute, *, fingerprint: str) -> JsonObject:
    raw_details = {
        "service": "service-monitoring",
        "site": route.site,
        "surface_kind": route.signal,
        "target_environment": "production",
        "project_id": route.owner_project,
        "owner_project": route.owner_project,
        "project_group": route.project_group,
        "customer_group": route.project_group,
        "group_label": route.group_label,
        "customer_label": route.group_label,
        "incident_key": route.incident_key,
        "incident_fingerprint": fingerprint,
        "alertable": True,
        "critical": True,
        "suppressed": False,
        "synthetic": False,
        "telegram_alert": True,
        "alert_policy": "critical",
        "expected_behavior": route.expected_behavior[:800],
        "dashboard_url": _DASHBOARD_URL,
        "dashboard_context": f"{route.group_label} / {route.site} / {route.signal}",
        "artifact_links": [_DASHBOARD_URL, MONITORING_SOURCE_URL],
        "source_repository_url": MONITORING_SOURCE_URL,
        "source_config_path": DOMAIN_CONFIG_PATH,
        "source_hints": list(route.source_hints),
        "logs_hint": route.logs_hint[:800],
        "deployment_hint": "Compare the monitoring source deployment SHA with recent app and infrastructure deploys.",
        "likely_fix_path": route.likely_fix_path[:800],
        "outgoing_message_boundary": OUTGOING_MESSAGE_BOUNDARY,
    }
    if route.domain:
        raw_details["domain"] = route.domain
    return json_object(cast("JsonInput", raw_details))


def _failure_fingerprint(route: ProductionIncidentRoute, *, evidence: JsonObject) -> str:
    material = {
        "incident_key": route.incident_key,
        "signal": route.signal,
        "domain": route.domain,
        "reason": safe_text_excerpt(evidence.get("reason"), max_chars=300),
        "error": safe_text_excerpt(evidence.get("error"), max_chars=500),
        "failures": int_value(evidence.get("failures")),
        "upstream_issues": int_value(evidence.get("upstream_issues")),
        "access_502_504_percent": float_value(evidence.get("access_502_504_percent")),
        "upstream_events": int_value(evidence.get("upstream_events")),
    }
    encoded = json.dumps(material, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _failed_checks(route: ProductionIncidentRoute, *, evidence: JsonObject) -> list[str]:
    reason = safe_text_excerpt(evidence.get("reason"), max_chars=300)
    if not reason:
        reason = f"debounced {route.signal} production check failed"
    checks = [reason]
    failures = int_value(evidence.get("failures"))
    upstream_issues = int_value(evidence.get("upstream_issues"))
    error = safe_text_excerpt(evidence.get("error"), max_chars=500)
    if failures is not None:
        checks.append(f"failed checks={failures}")
    if upstream_issues is not None:
        checks.append(f"upstream issues={upstream_issues}")
    if error:
        checks.append(error)
    return checks[:8]


def _evidence_lines(route: ProductionIncidentRoute, *, evidence: JsonObject) -> list[str]:
    lines = [f"{route.site}: {_failed_checks(route, evidence=evidence)[0]}"]
    for key in ("failures", "upstream_issues", "access_502_504_percent", "upstream_events"):
        value = evidence.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            lines.append(f"{key}={value}")
    return lines[:8]


def _copy_numeric_evidence(details: JsonObject, *, evidence: JsonObject) -> None:
    for key in ("failures", "upstream_issues", "upstream_events"):
        value = int_value(evidence.get(key))
        if value is not None:
            details[key] = value
    percentage = float_value(evidence.get("access_502_504_percent"))
    if percentage is not None:
        details["access_502_504_percent"] = percentage
