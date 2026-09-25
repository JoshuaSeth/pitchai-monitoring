# Copyright (c) 2026 PitchAI. All rights reserved.
"""Monitoring dashboard operator-summary aggregation tests."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from e2e_registry.monitor_dashboard import build_dashboard_summary
from tests.monitor_dashboard_summary_support import build_monitor_data
from tests.monitor_dashboard_test_contract import (
    require_monitor_float,
    require_monitor_record,
    require_monitor_records,
)

if TYPE_CHECKING:
    from e2e_registry.monitor_types import MonitorRecord

_EXPECTED_OBSERVATIONS = 2
_EXPECTED_AVAILABILITY = 50.0


def _verify_health_and_inventory(summary: MonitorRecord, *, now: float) -> None:
    freshness = require_monitor_record(summary.get("freshness"), label="freshness")
    expected_freshness = {
        "status": "stale",
        "state_updated_at_ts": now - 400,
        "age_seconds": 400.0,
        "interval_seconds": 60,
        "stale_after_seconds": 180,
        "source": "state.updated_at",
    }
    if freshness != expected_freshness:
        message = f"unexpected monitor freshness summary: {freshness!r}"
        raise AssertionError(message)
    service_health = require_monitor_record(
        summary.get("service_health"), label="service health",
    )
    expected_health = {
        "enabled": 1,
        "healthy": 0,
        "down": 1,
        "alertable_down": 1,
        "expected_down": 0,
        "unknown": 0,
        "disabled": 0,
    }
    if service_health != expected_health:
        message = f"unexpected service health summary: {service_health!r}"
        raise AssertionError(message)
    groups = require_monitor_records(summary.get("domain_groups"), label="groups")
    expected_groups = [
        {
            "id": "core",
            "label": "PitchAI core",
            "description": "Primary platform routes",
            "order": 10,
            "enabled": 1,
            "healthy": 0,
            "down": 1,
            "alertable_down": 1,
            "expected_down": 0,
            "unknown": 0,
            "disabled": 0,
            "total": 1,
            "status": "attention",
        },
    ]
    if groups != expected_groups:
        message = f"unexpected domain group summary: {groups!r}"
        raise AssertionError(message)
    inventory = require_monitor_record(summary.get("inventory"), label="inventory")
    expected_inventory = {
        "version": 1,
        "reviewed_at": "2026-08-24",
        "active_domains": 1,
        "groups": 1,
        "retired_domains": 0,
        "orphaned_state_domains": 0,
    }
    if inventory != expected_inventory:
        message = f"unexpected dashboard inventory summary: {inventory!r}"
        raise AssertionError(message)
    domains = require_monitor_records(summary.get("domains"), label="domains")
    if domains[0].get("group_label") != "PitchAI core":
        message = f"domain group label was not resolved: {domains[0]!r}"
        raise AssertionError(message)


def _verify_incidents_and_daily_status(summary: MonitorRecord, *, now: float) -> None:
    incidents = require_monitor_records(summary.get("incidents"), label="incidents")
    if incidents[1].get("group") != "core":
        message = f"domain incident group was not resolved: {incidents[1]!r}"
        raise AssertionError(message)
    incident_kinds = [incident.get("kind") for incident in incidents]
    expected_kinds = [
        "monitor_freshness",
        "domain_down",
        "signal_degraded",
        "e2e_failure",
    ]
    if incident_kinds != expected_kinds:
        message = f"unexpected incident order: {incident_kinds!r}"
        raise AssertionError(message)
    e2e = require_monitor_record(summary.get("e2e"), label="E2E summary")
    if e2e.get("passing_tests") != 1 or e2e.get("failing_tests") != 1:
        message = f"unexpected E2E pass/fail totals: {e2e!r}"
        raise AssertionError(message)
    problems = require_monitor_records(e2e.get("problems"), label="E2E problems")
    if problems[0].get("test_id") != "failing":
        message = f"unexpected E2E problem identity: {problems[0]!r}"
        raise AssertionError(message)
    daily = require_monitor_record(summary.get("daily_status"), label="daily status")
    if daily.get("observations") != _EXPECTED_OBSERVATIONS:
        message = f"unexpected daily observation count: {daily!r}"
        raise AssertionError(message)
    if daily.get("successful_observations") != 1:
        message = f"unexpected successful observation count: {daily!r}"
        raise AssertionError(message)
    availability = require_monitor_float(
        daily.get("availability_pct"), label="daily availability",
    )
    if not math.isclose(availability, _EXPECTED_AVAILABILITY):
        message = f"unexpected daily availability: {availability!r}"
        raise AssertionError(message)
    if daily.get("problem_events") != 1 or daily.get("recoveries") != 1:
        message = f"unexpected daily event totals: {daily!r}"
        raise AssertionError(message)
    if daily.get("latest_event_at_ts") != now - 50:
        message = f"unexpected latest daily event timestamp: {daily!r}"
        raise AssertionError(message)
    if daily.get("status") != "attention":
        message = f"unexpected daily status: {daily!r}"
        raise AssertionError(message)


def test_operator_summary_reports_real_staleness_incidents_and_rolling_day() -> None:
    """Report real staleness, incidents, E2E health, and rolling-day totals."""
    now = 2_000_000_000.0
    data = build_monitor_data(
        now=now,
        state={
            "updated_at": now - 400,
            "history": {
                "down.pitchai.net": [
                    [now - 120, True, 100.0, 300.0, 200],
                    [now - 60, False, 900.0, 1800.0, 503],
                ],
            },
            "last_ok": {"down.pitchai.net": False},
            "fail_streak": {"down.pitchai.net": 2},
            "success_streak": {"down.pitchai.net": 0},
            "host_health": {"last_ok": False, "fail_streak": 3, "success_streak": 0},
            "events": [
                {"ts": now - 90000, "kind": "domain_down", "domain": "old.pitchai.net"},
                {"ts": now - 100, "kind": "domain_down", "domain": "down.pitchai.net"},
                {"ts": now - 50, "kind": "proxy_recovered"},
            ],
        },
        reviewed_at="2026-08-24",
        groups={
            "core": {
                "label": "PitchAI core",
                "description": "Primary platform routes",
                "order": 10,
            },
        },
        domains=[
            {
                "domain": "down.pitchai.net",
                "label": "Down test route",
                "group": "core",
                "environment": "production",
                "kind": "application",
                "sources": ["test fixture"],
            },
        ],
    )
    e2e: MonitorRecord = {
        "ok": True,
        "total_tests": 2,
        "failing_tests": 1,
        "tests": [
            {
                "test_id": "passing",
                "test_name": "Passing route",
                "base_url": "https://passing.pitchai.net",
                "enabled": 1,
                "effective_ok": 1,
                "last_status": "pass",
                "last_finished_at_ts": now - 20,
            },
            {
                "test_id": "failing",
                "test_name": "Failing route",
                "base_url": "https://failing.pitchai.net",
                "enabled": 1,
                "effective_ok": 0,
                "fail_streak": 2,
                "last_status": "fail",
                "last_finished_at_ts": now - 10,
            },
        ],
    }

    summary = build_dashboard_summary(
        data=data,
        now_ts=now,
        e2e_status_summary=e2e,
        e2e_dispatch_runs=[],
    )

    _verify_health_and_inventory(summary, now=now)
    _verify_incidents_and_daily_status(summary, now=now)
