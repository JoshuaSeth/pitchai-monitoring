# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed assertions over the unchanged operator dashboard fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from domain_checks.dft_test_support import require
from e2e_registry.monitor_dashboard import build_dashboard_summary

from .monitor_dashboard_expected_down_fixture import make_expected_down_fixture
from .monitor_dashboard_operator_fixture import make_operator_fixture
from .monitor_dashboard_subcheck_fixture import make_subcheck_fixture

if TYPE_CHECKING:
    from e2e_registry.dashboard_records import Record
_EXPECTED_OBSERVATIONS = 2
_EXPECTED_AVAILABILITY_PERCENT = 50.0


def test_operator_summary_reports_real_staleness_incidents_and_rolling_day() -> None:
    """Preserve the original operator summary assertions."""
    now = 2000000000.0
    data, e2e = make_operator_fixture(now)
    summary = build_dashboard_summary(data=data, now_ts=now, e2e_status_summary=e2e, e2e_dispatch_runs=[])
    require(
        condition=summary["freshness"]
        == {
            "status": "stale",
            "state_updated_at_ts": now - 400,
            "age_seconds": 400.0,
            "interval_seconds": 60,
            "stale_after_seconds": 180,
            "source": "state.updated_at",
        },
        message="test_operator_summary_reports_real_staleness_incidents_and_rolling_day: assertion 1",
    )
    require(
        condition=cast("Record", summary["service_health"])
        == {
            "enabled": 1,
            "healthy": 0,
            "down": 1,
            "alertable_down": 1,
            "expected_down": 0,
            "unknown": 0,
            "disabled": 0,
        },
        message="test_operator_summary_reports_real_staleness_incidents_and_rolling_day: assertion 2",
    )
    require(
        condition=cast("list[Record]", summary["domain_groups"])
        == [
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
        ],
        message="test_operator_summary_reports_real_staleness_incidents_and_rolling_day: assertion 3",
    )
    require(
        condition=summary["inventory"]
        == {
            "version": 1,
            "reviewed_at": "2026-08-24",
            "active_domains": 1,
            "groups": 1,
            "retired_domains": 0,
            "orphaned_state_domains": 0,
        },
        message="test_operator_summary_reports_real_staleness_incidents_and_rolling_day: assertion 4",
    )
    require(
        condition=cast("list[Record]", summary["domains"])[0]["group_label"] == "PitchAI core",
        message="test_operator_summary_reports_real_staleness_incidents_and_rolling_day: assertion 5",
    )
    require(
        condition=cast("list[Record]", summary["incidents"])[1]["group"] == "core",
        message="test_operator_summary_reports_real_staleness_incidents_and_rolling_day: assertion 6",
    )
    require(
        condition=cast("Record", summary["e2e"])["passing_tests"] == 1,
        message="test_operator_summary_reports_real_staleness_incidents_and_rolling_day: assertion 7",
    )
    require(
        condition=cast("Record", summary["e2e"])["failing_tests"] == 1,
        message="test_operator_summary_reports_real_staleness_incidents_and_rolling_day: assertion 8",
    )
    require(
        condition=cast("list[Record]", cast("Record", summary["e2e"])["problems"])[0]["test_id"] == "failing",
        message="test_operator_summary_reports_real_staleness_incidents_and_rolling_day: assertion 9",
    )
    require(
        condition=[incident["kind"] for incident in cast("list[Record]", summary["incidents"])]
        == ["monitor_freshness", "domain_down", "signal_degraded", "e2e_failure"],
        message="test_operator_summary_reports_real_staleness_incidents_and_rolling_day: assertion 10",
    )
    require(
        condition=cast("Record", summary["daily_status"])["observations"] == _EXPECTED_OBSERVATIONS,
        message="test_operator_summary_reports_real_staleness_incidents_and_rolling_day: assertion 11",
    )
    require(
        condition=cast("Record", summary["daily_status"])["successful_observations"] == 1,
        message="test_operator_summary_reports_real_staleness_incidents_and_rolling_day: assertion 12",
    )
    require(
        condition=cast("Record", summary["daily_status"])["availability_pct"] == _EXPECTED_AVAILABILITY_PERCENT,
        message="test_operator_summary_reports_real_staleness_incidents_and_rolling_day: assertion 13",
    )
    require(
        condition=cast("Record", summary["daily_status"])["problem_events"] == 1,
        message="test_operator_summary_reports_real_staleness_incidents_and_rolling_day: assertion 14",
    )
    require(
        condition=cast("Record", summary["daily_status"])["recoveries"] == 1,
        message="test_operator_summary_reports_real_staleness_incidents_and_rolling_day: assertion 15",
    )
    require(
        condition=cast("Record", summary["daily_status"])["latest_event_at_ts"] == now - 50,
        message="test_operator_summary_reports_real_staleness_incidents_and_rolling_day: assertion 16",
    )
    require(
        condition=cast("Record", summary["daily_status"])["status"] == "attention",
        message="test_operator_summary_reports_real_staleness_incidents_and_rolling_day: assertion 17",
    )


def test_service_health_rolls_failing_api_subcheck_into_domain_and_group_status() -> None:
    """Preserve the original subcheck summary assertions."""
    now = 2000000000.0
    data = make_subcheck_fixture(now)
    summary = build_dashboard_summary(data=data, now_ts=now, e2e_status_summary=None, e2e_dispatch_runs=[])
    domain = cast("list[Record]", summary["domains"])[0]
    require(
        condition=cast("Record", domain["last"])
        == {
            "ts": now,
            "primary_ts": now,
            "ok": False,
            "primary_ok": True,
            "failure_sources": ["api_contract"],
            "http_ms": 100.0,
            "browser_ms": 200.0,
            "status_code": None,
            "primary_status_code": 200,
        },
        message="test_service_health_rolls_failing_api_subcheck_into_domain_and_group_status: assertion 18",
    )
    require(
        condition=cast("Record", summary["service_health"])["down"] == 1,
        message="test_service_health_rolls_failing_api_subcheck_into_domain_and_group_status: assertion 19",
    )
    require(
        condition=cast("list[Record]", summary["domain_groups"])[0]["status"] == "attention",
        message="test_service_health_rolls_failing_api_subcheck_into_domain_and_group_status: assertion 20",
    )
    require(
        condition=cast("list[Record]", summary["incidents"])[0]["kind"] == "domain_down",
        message="test_service_health_rolls_failing_api_subcheck_into_domain_and_group_status: assertion 21",
    )
    require(
        condition="API/service subcheck" in cast("str", cast("list[Record]", summary["incidents"])[0]["detail"]),
        message="test_service_health_rolls_failing_api_subcheck_into_domain_and_group_status: assertion 22",
    )


def test_dashboard_distinguishes_expected_down_from_alertable_down() -> None:
    """Preserve the original expected down summary assertions."""
    now = 2000000000.0
    data = make_expected_down_fixture(now)
    summary = build_dashboard_summary(data=data, now_ts=now, e2e_status_summary=None, e2e_dispatch_runs=[])
    require(
        condition=cast("Record", summary["service_health"])
        == {
            "enabled": 2,
            "healthy": 0,
            "down": 2,
            "alertable_down": 1,
            "expected_down": 1,
            "unknown": 0,
            "disabled": 0,
        },
        message="test_dashboard_distinguishes_expected_down_from_alertable_down: assertion 23",
    )
    by_domain: dict[str, Record] = {}
    for domain in cast("list[Record]", summary["domains"]):
        by_domain[cast("str", domain["domain"])] = domain
    require(
        condition=cast("Record", by_domain["agentcloud.pitchai.net"]["last"])["ok"] is False,
        message="test_dashboard_distinguishes_expected_down_from_alertable_down: assertion 24",
    )
    require(
        condition=by_domain["agentcloud.pitchai.net"]["alert_policy"]
        == {"telegram": "dashboard-only", "telegram_enabled": False, "reason": "Not actively used right now."},
        message="test_dashboard_distinguishes_expected_down_from_alertable_down: assertion 25",
    )
    incidents: dict[str, Record] = {}
    for incident in cast("list[Record]", summary["incidents"]):
        if incident.get("kind") == "domain_down":
            incidents[cast("str", incident["domain"])] = incident
    require(
        condition=incidents["agentcloud.pitchai.net"]["severity"] == "expected",
        message="test_dashboard_distinguishes_expected_down_from_alertable_down: assertion 26",
    )
    require(
        condition=incidents["agentcloud.pitchai.net"]["telegram_alert"] is False,
        message="test_dashboard_distinguishes_expected_down_from_alertable_down: assertion 27",
    )
    require(
        condition="no Telegram alert is routed" in cast("str", incidents["agentcloud.pitchai.net"]["detail"]),
        message="test_dashboard_distinguishes_expected_down_from_alertable_down: assertion 28",
    )
    require(
        condition=incidents["pitchai.net"]["severity"] == "critical",
        message="test_dashboard_distinguishes_expected_down_from_alertable_down: assertion 29",
    )
    require(
        condition=incidents["pitchai.net"]["telegram_alert"] is True,
        message="test_dashboard_distinguishes_expected_down_from_alertable_down: assertion 30",
    )
