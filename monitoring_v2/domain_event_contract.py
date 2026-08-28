# Copyright (c) 2026 PitchAI. All rights reserved.
"""Complete production-domain incident contract for the native Events Inbox."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, cast

from .domain_event_models import DomainTransitionEvent
from .incident_event_context import DOMAIN_CONFIG_PATH, MONITORING_SOURCE_URL, OUTGOING_MESSAGE_BOUNDARY
from .json_types import (
    float_value,
    int_value,
    json_object,
    normalize_json,
)
from .safe_evidence import safe_public_url, safe_text_excerpt

if TYPE_CHECKING:
    from .domain_event_models import DomainIncidentPolicy
    from .json_types import JsonInput, JsonObject

_DASHBOARD_URL = "https://monitoring.pitchai.net/dashboard#domains"


def domain_down_event(
    policy: DomainIncidentPolicy,
    evidence: JsonObject,
    *,
    occurred_at: float,
    re_escalation: bool,
) -> DomainTransitionEvent:
    """Build one actionable critical domain-down transition.

    Returns:
        A complete event ready for durable immutable-envelope staging.
    """
    fingerprint = _failure_fingerprint(policy, evidence=evidence)
    details = _common_details(policy, fingerprint=fingerprint)
    reason = safe_text_excerpt(evidence.get("reason"), max_chars=300) or "production domain check failed"
    error = safe_text_excerpt(evidence.get("error"), max_chars=800)
    status_code = int_value(evidence.get("status_code"))
    fail_streak = int_value(evidence.get("fail_streak"))
    detected_at = float_value(evidence.get("ts")) or occurred_at
    details.update({
        "severity": "critical",
        "detection_reason": reason,
        "detected_at_ts": detected_at,
        "failed_checks": normalize_json(_failed_checks(reason=reason, status_code=status_code, error=error)),
        "evidence": normalize_json(_evidence_lines(reason=reason, status_code=status_code, error=error)),
        "repair_dispatch": "Immediately triage, repair, verify production, deploy if needed, and report privately.",
        "re_escalation": re_escalation,
        "incident_update": "persistent_failure_re_escalation" if re_escalation else "new_failure",
    })
    if status_code is not None:
        details["status_code"] = status_code
    if fail_streak is not None:
        details["fail_streak"] = fail_streak
    if error:
        details["error"] = error
    final_url = safe_public_url(evidence.get("final_url"))
    if final_url:
        details["observed_final_url"] = final_url
    return DomainTransitionEvent(kind="domain_down", occurred_at=occurred_at, details=details)


def domain_up_event(
    policy: DomainIncidentPolicy,
    *,
    incident_fingerprint: str,
    occurred_at: float,
) -> DomainTransitionEvent:
    """Build one recovery transition for an existing critical incident lane.

    Returns:
        A complete recovery event keyed to the original incident.
    """
    details = _common_details(policy, fingerprint=incident_fingerprint)
    details.update({
        "severity": "info",
        "recovered_at_ts": occurred_at,
        "evidence": [f"{policy.domain}: debounced production domain check recovered"],
        "repair_dispatch": "Verify live recovery and reconcile the existing incident lane.",
        "re_escalation": False,
        "incident_update": "recovered",
    })
    return DomainTransitionEvent(kind="domain_up", occurred_at=occurred_at, details=details)


def _common_details(policy: DomainIncidentPolicy, *, fingerprint: str) -> JsonObject:
    raw_details = {
        "service": "service-monitoring",
        "site": policy.domain,
        "domain": policy.domain,
        "label": policy.label,
        "surface_kind": policy.surface_kind,
        "target_environment": "production",
        "project_id": policy.owner_project,
        "owner_project": policy.owner_project,
        "project_group": policy.group,
        "customer_group": policy.group,
        "group_label": policy.group_label,
        "customer_label": policy.group_label,
        "incident_key": f"domain:{policy.domain}",
        "incident_fingerprint": fingerprint,
        "alertable": True,
        "critical": True,
        "suppressed": False,
        "synthetic": False,
        "telegram_alert": True,
        "alert_policy": policy.alert_mode,
        "expected_behavior": _expected_behavior(policy),
        "dashboard_url": _DASHBOARD_URL,
        "dashboard_context": f"{policy.group_label} / {policy.label}",
        "artifact_links": [_DASHBOARD_URL, MONITORING_SOURCE_URL],
        "source_repository_url": MONITORING_SOURCE_URL,
        "source_config_path": DOMAIN_CONFIG_PATH,
        "source_hints": list(policy.sources),
        "logs_hint": "Inspect service-monitoring logs and the current dashboard incident evidence for this domain.",
        "deployment_hint": "Compare the event source deployment SHA with the most recent monitoring and site deploys.",
        "outgoing_message_boundary": OUTGOING_MESSAGE_BOUNDARY,
    }
    return json_object(cast("JsonInput", raw_details))


def _expected_behavior(policy: DomainIncidentPolicy) -> str:
    requirements = [
        f"{policy.source_url} must pass the configured production check",
        f"with status in {list(policy.allowed_status_codes)}",
    ]
    if policy.expected_final_host_suffix:
        requirements.append(f"and resolve to host suffix {policy.expected_final_host_suffix}")
    if policy.expected_final_path:
        requirements.append(f"at canonical path {policy.expected_final_path}")
    if policy.expected_title_contains:
        requirements.append(f"with page title containing {policy.expected_title_contains!r}")
    return " ".join(requirements)[:800]


def _failure_fingerprint(policy: DomainIncidentPolicy, *, evidence: JsonObject) -> str:
    material = {
        "domain": policy.domain,
        "reason": safe_text_excerpt(evidence.get("reason"), max_chars=300),
        "status_code": int_value(evidence.get("status_code")),
        "error": safe_text_excerpt(evidence.get("error"), max_chars=500),
        "source_url": policy.source_url,
        "expected_status_codes": list(policy.allowed_status_codes),
    }
    encoded = json.dumps(material, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _failed_checks(*, reason: str, status_code: int | None, error: str | None) -> list[str]:
    checks = [reason]
    if status_code is not None:
        checks.append(f"observed HTTP status {status_code}")
    if error:
        checks.append(error)
    return checks[:6]


def _evidence_lines(*, reason: str, status_code: int | None, error: str | None) -> list[str]:
    lines = [f"debounced domain monitor failure: {reason}"]
    if status_code is not None:
        lines.append(f"status_code={status_code}")
    if error:
        lines.append(f"sanitized_error={error}")
    return lines[:6]
