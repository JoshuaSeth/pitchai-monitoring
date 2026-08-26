# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build disclosure-ready incidents for public domain checks."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from domain_checks.json_types import (
    bool_value,
    float_value,
    int_value,
    json_object,
    optional_object,
    text_value,
    value_list,
)
from domain_checks.safe_evidence import safe_text_excerpt
from e2e_registry.monitoring_v2.domain_trends import domain_trend, history_for_domain
from e2e_registry.monitoring_v2.event_analysis import (
    domain_first_seen,
    last_successful_sample,
    latest_problem_event,
)

if TYPE_CHECKING:
    from domain_checks.json_types import JsonObject, JsonValue

_SOURCE_LABELS = {
    "primary": "page/readiness check",
    "api_contract": "API/service subcheck",
    "synthetic": "end-to-end transaction",
}


class _FailureContext(NamedTuple):
    """Current alert and failure classification for one domain."""

    domain_name: str
    policy: JsonObject
    alertable: bool
    failure_sources: list[str]
    labels: list[str]
    group_label: str
    reason: str | None


class _IncidentEvidence(NamedTuple):
    """Sanitized retained evidence for one domain incident."""

    event: JsonObject
    history: list[JsonValue]
    latest_seen: float | None
    check_name: str | None
    status_code: int | None
    response_excerpt: str | None
    error_message: str | None


def _domain_action(domain: str, failure_sources: list[str], *, alertable: bool) -> str:
    if not alertable:
        return (
            "Confirm the dashboard-only condition remains intentional; change routing only if this service becomes "
            "operationally critical."
        )
    if "api_contract" in failure_sources:
        return (
            f"Reproduce the failing API/service subcheck for {domain}, then inspect its deployment and backend/proxy "
            "logs."
        )
    if "synthetic" in failure_sources:
        return f"Reproduce the first failed journey step for {domain} and compare it with the last successful run."
    return f"Reproduce the public readiness request for {domain}, then inspect its deployment and proxy/container logs."


def _failure_context(domain: JsonObject, last: JsonObject) -> _FailureContext:
    domain_name = text_value(domain.get("domain"))
    policy = optional_object(domain.get("alert_policy"))
    alertable = bool_value(policy.get("telegram_enabled")) is not False
    failure_source_values = value_list(last.get("failure_sources"))
    raw_sources = (text_value(item) for item in failure_source_values)
    failure_sources = [source for source in raw_sources if source]
    labels = [_SOURCE_LABELS.get(source, source.replace("_", " ")) for source in failure_sources]
    return _FailureContext(
        domain_name=domain_name,
        policy=policy,
        alertable=alertable,
        failure_sources=failure_sources,
        labels=labels,
        group_label=text_value(domain.get("group_label"), default="Unconfigured"),
        reason=safe_text_excerpt(policy.get("reason"), max_chars=240),
    )


def _incident_evidence(
    context: _FailureContext,
    last: JsonObject,
    *,
    state: JsonObject,
    events: list[JsonObject],
) -> _IncidentEvidence:
    event = latest_problem_event(
        domain=context.domain_name,
        failure_sources=context.failure_sources,
        events=events,
    )
    history = history_for_domain(state, context.domain_name)
    candidate_timestamps = (float_value(event.get("ts")), float_value(last.get("ts")))
    timestamps = [timestamp for timestamp in candidate_timestamps if timestamp is not None]
    status_code = int_value(event.get("status_code"))
    if status_code is None:
        status_code = int_value(last.get("status_code"))
    return _IncidentEvidence(
        event=event,
        history=history,
        latest_seen=max(timestamps, default=None),
        check_name=safe_text_excerpt(event.get("check_name"), max_chars=120),
        status_code=status_code,
        response_excerpt=safe_text_excerpt(
            event.get("response_excerpt"),
            max_chars=360,
        ),
        error_message=safe_text_excerpt(
            event.get("error") or event.get("reason"),
            max_chars=360,
        ),
    )


def _incident_detail(context: _FailureContext) -> str:
    detail = f"{context.group_label} · {', '.join(context.labels) or 'health check'} is down."
    if not context.alertable:
        detail += " Expected/dashboard-only status; no Telegram alert is routed."
    return detail


def build_domain_incident(
    domain: JsonObject,
    *,
    state: JsonObject,
    events: list[JsonObject],
    now_ts: float,
) -> JsonObject:
    """Build one current domain-down incident from retained evidence.

    Returns:
        One disclosure-ready domain incident.
    """
    last = optional_object(domain.get("last"))
    context = _failure_context(domain, last)
    evidence = _incident_evidence(context, last, state=state, events=events)
    return json_object(
        {
            "incident_id": f"domain_down:{context.domain_name}",
            "kind": "domain_down",
            "severity": "critical" if context.alertable else "expected",
            "title": (
                f"{context.domain_name} is down"
                if context.alertable
                else f"{context.domain_name} is down — expected / dashboard only"
            ),
            "detail": _incident_detail(context),
            "current_status": "down",
            "affected_check": evidence.check_name or ", ".join(context.labels) or "health check",
            "affected_checks": context.labels,
            "affected_service": text_value(
                domain.get("label"),
                default=context.domain_name,
            ),
            "domain": context.domain_name,
            "environment": text_value(domain.get("environment"), default="unspecified"),
            "group": text_value(domain.get("group"), default="unconfigured"),
            "group_label": context.group_label,
            "owner_project": context.group_label,
            "status_code": evidence.status_code,
            "error_message": evidence.error_message,
            "response_excerpt": evidence.response_excerpt,
            "content_type": safe_text_excerpt(
                evidence.event.get("content_type"),
                max_chars=120,
            ),
            "first_seen_at_ts": domain_first_seen(
                domain=context.domain_name,
                failure_sources=context.failure_sources,
                events=events,
                history=evidence.history,
            ),
            "latest_seen_at_ts": evidence.latest_seen,
            "observed_at_ts": evidence.latest_seen,
            "last_successful_sample": last_successful_sample(evidence.history),
            "trend": domain_trend(evidence.history, now_ts=now_ts),
            "alert_policy": {
                "channel": "Telegram",
                "enabled": context.alertable,
                "mode": text_value(
                    context.policy.get("telegram"),
                    default="enabled" if context.alertable else "dashboard-only",
                ),
                "reason": context.reason,
            },
            "telegram_alert": context.alertable,
            "expected": not context.alertable,
            "suggested_next_action": _domain_action(
                context.domain_name,
                context.failure_sources,
                alertable=context.alertable,
            ),
            "evidence_state": "retained" if evidence.response_excerpt or evidence.error_message else "on_expand",
            "evidence_endpoint": f"/dashboard/api/v1/monitoring/incidents/{context.domain_name}/evidence",
        },
    )


def build_unknown_incident(domain: JsonObject) -> JsonObject:
    """Build a warning when an enabled domain has no current observation.

    Returns:
        One warning incident for the missing observation.
    """
    domain_name = text_value(domain.get("domain"))
    group_label = text_value(domain.get("group_label"), default="Unconfigured")
    policy = optional_object(domain.get("alert_policy"))
    alertable = bool_value(policy.get("telegram_enabled")) is not False
    return json_object(
        {
            "incident_id": f"domain_unknown:{domain_name}",
            "kind": "domain_unknown",
            "severity": "warning" if alertable else "expected",
            "title": f"{domain_name} has no current result",
            "detail": f"{group_label} · this enabled check has not produced a current observation.",
            "current_status": "unknown",
            "affected_check": "domain health collector",
            "affected_service": text_value(domain.get("label"), default=domain_name),
            "domain": domain_name,
            "owner_project": group_label,
            "alert_policy": {"channel": "Telegram", "enabled": alertable},
            "telegram_alert": alertable,
            "expected": not alertable,
            "suggested_next_action": (
                "Inspect monitor freshness and this domain's check configuration before treating the missing "
                "result as an outage."
            ),
            "trend": {"direction": "unknown", "observations": 0, "points": []},
            "evidence_state": "missing",
        },
    )
