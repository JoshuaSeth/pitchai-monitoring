# Copyright (c) 2026 PitchAI. All rights reserved.
"""Monitoring dashboard effective-health and alert-policy tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from e2e_registry.monitor_dashboard import build_dashboard_summary
from tests.monitor_dashboard_summary_support import build_monitor_data
from tests.monitor_dashboard_test_contract import (
    require_monitor_record,
    require_monitor_records,
)

if TYPE_CHECKING:
    from e2e_registry.monitor_types import MonitorRecord


def _verify_api_subcheck_failure(summary: MonitorRecord, *, now: float) -> None:
    domains = require_monitor_records(summary.get("domains"), label="summary domains")
    domain = domains[0]
    expected_last = {
        "ts": now,
        "primary_ts": now,
        "ok": False,
        "primary_ok": True,
        "failure_sources": ["api_contract"],
        "http_ms": 100.0,
        "browser_ms": 200.0,
        "status_code": None,
        "primary_status_code": 200,
    }
    if domain.get("last") != expected_last:
        message = f"API failure was not rolled into domain health: {domain.get('last')!r}"
        raise AssertionError(message)
    service_health = require_monitor_record(
        summary.get("service_health"), label="service health",
    )
    if service_health.get("down") != 1:
        message = f"effective service down count is wrong: {service_health!r}"
        raise AssertionError(message)
    groups = require_monitor_records(summary.get("domain_groups"), label="domain groups")
    if groups[0].get("status") != "attention":
        message = f"API failure did not affect group health: {groups[0]!r}"
        raise AssertionError(message)
    incidents = require_monitor_records(summary.get("incidents"), label="incidents")
    incident = incidents[0]
    if incident.get("kind") != "domain_down":
        message = f"API failure produced the wrong incident kind: {incident!r}"
        raise AssertionError(message)
    detail = incident.get("detail")
    if not isinstance(detail, str) or "API/service subcheck" not in detail:
        message = f"API failure incident omitted its source: {detail!r}"
        raise AssertionError(message)


def _verify_expected_down_policy(summary: MonitorRecord) -> None:
    service_health = require_monitor_record(
        summary.get("service_health"), label="service health",
    )
    expected_health = {
        "enabled": 2,
        "healthy": 0,
        "down": 2,
        "alertable_down": 1,
        "expected_down": 1,
        "unknown": 0,
        "disabled": 0,
    }
    if service_health != expected_health:
        message = f"unexpected alert-aware service health: {service_health!r}"
        raise AssertionError(message)
    domains = require_monitor_records(summary.get("domains"), label="summary domains")
    by_domain = {str(domain.get("domain")): domain for domain in domains}
    agentcloud = by_domain["agentcloud.pitchai.net"]
    agentcloud_last = require_monitor_record(
        agentcloud.get("last"), label="AgentCloud last",
    )
    if agentcloud_last.get("ok") is not False:
        message = f"AgentCloud must remain visibly down: {agentcloud_last!r}"
        raise AssertionError(message)
    expected_policy = {
        "telegram": "dashboard-only",
        "telegram_enabled": False,
        "reason": "Not actively used right now.",
    }
    if agentcloud.get("alert_policy") != expected_policy:
        message = f"AgentCloud alert policy was not preserved: {agentcloud!r}"
        raise AssertionError(message)
    all_incidents = require_monitor_records(
        summary.get("incidents"), label="incidents",
    )
    domain_down_incidents = [
        incident for incident in all_incidents if incident.get("kind") == "domain_down"
    ]
    incidents = {
        str(incident.get("domain")): incident
        for incident in domain_down_incidents
    }
    expected_incident = incidents["agentcloud.pitchai.net"]
    if expected_incident.get("severity") != "expected":
        message = f"AgentCloud incident must be expected: {expected_incident!r}"
        raise AssertionError(message)
    if expected_incident.get("telegram_alert") is not False:
        message = f"AgentCloud incident must suppress Telegram: {expected_incident!r}"
        raise AssertionError(message)
    detail = expected_incident.get("detail")
    if not isinstance(detail, str) or "no Telegram alert is routed" not in detail:
        message = f"AgentCloud incident omitted its routing explanation: {detail!r}"
        raise AssertionError(message)
    critical_incident = incidents["pitchai.net"]
    if critical_incident.get("severity") != "critical":
        message = f"PitchAI incident must remain critical: {critical_incident!r}"
        raise AssertionError(message)
    if critical_incident.get("telegram_alert") is not True:
        message = f"PitchAI incident must route Telegram: {critical_incident!r}"
        raise AssertionError(message)


def test_service_health_rolls_failing_api_subcheck_into_domain_and_group_status() -> (
    None
):
    """Roll an API subcheck failure into domain, group, and incident health."""
    now = 2_000_000_000.0
    data = build_monitor_data(
        now=now,
        state={
            "updated_at": now,
            "history": {"dispatch.pitchai.net": [[now, True, 100.0, 200.0, 200]]},
            "last_ok": {"dispatch.pitchai.net": True},
            "fail_streak": {"dispatch.pitchai.net": 0},
            "success_streak": {"dispatch.pitchai.net": 4},
            "api_contract": {
                "last_ok": {"dispatch.pitchai.net": False},
                "fail_streak": {"dispatch.pitchai.net": 2},
                "success_streak": {"dispatch.pitchai.net": 0},
                "last_run_ts": {"dispatch.pitchai.net": now},
            },
        },
        reviewed_at="2026-08-24",
        groups={
            "operations": {
                "label": "Operations",
                "description": "Operator services",
                "order": 10,
            },
        },
        domains=[
            {
                "domain": "dispatch.pitchai.net",
                "label": "Dispatcher",
                "group": "operations",
                "environment": "internal",
                "kind": "application",
                "sources": ["test fixture"],
            },
        ],
    )

    summary = build_dashboard_summary(
        data=data,
        now_ts=now,
        e2e_status_summary=None,
        e2e_dispatch_runs=[],
    )

    _verify_api_subcheck_failure(summary, now=now)


def test_dashboard_distinguishes_expected_down_from_alertable_down() -> None:
    """Distinguish dashboard-only failures from alertable critical failures."""
    now = 2_000_000_000.0
    domains = ["agentcloud.pitchai.net", "pitchai.net"]
    data = build_monitor_data(
        now=now,
        state={
            "updated_at": now,
            "history": {
                domain: [[now, False, 250.0, 400.0, 502]] for domain in domains
            },
            "last_ok": dict.fromkeys(domains, False),
            "fail_streak": dict.fromkeys(domains, 3),
            "success_streak": dict.fromkeys(domains, 0),
        },
        reviewed_at="2026-08-25",
        groups={
            "core": {
                "label": "PitchAI core",
                "description": "Critical production",
                "order": 10,
            },
            "infrastructure": {
                "label": "Infrastructure",
                "description": "Internal services",
                "order": 20,
            },
        },
        domains=[
            {
                "domain": "agentcloud.pitchai.net",
                "label": "AgentCloud",
                "group": "infrastructure",
                "environment": "internal",
                "kind": "application",
                "sources": ["test fixture"],
                "alert_policy": {
                    "telegram": "dashboard-only",
                    "reason": "Not actively used right now.",
                },
            },
            {
                "domain": "pitchai.net",
                "label": "PitchAI website",
                "group": "core",
                "environment": "production",
                "kind": "application",
                "sources": ["test fixture"],
            },
        ],
    )

    summary = build_dashboard_summary(
        data=data,
        now_ts=now,
        e2e_status_summary=None,
        e2e_dispatch_runs=[],
    )

    _verify_expected_down_policy(summary)
