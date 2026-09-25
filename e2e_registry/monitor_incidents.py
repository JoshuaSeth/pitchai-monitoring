# Copyright (c) 2026 PitchAI. All rights reserved.
"""Operator incident construction from normalized monitor summaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from e2e_registry.monitor_signals import signal_display_name
from e2e_registry.monitor_values import monitor_mapping, monitor_records, safe_int

if TYPE_CHECKING:
    from e2e_registry.monitor_types import MonitorRecord, MonitorRecords


@dataclass(frozen=True)
class IncidentContext:
    """Inputs that can independently produce current dashboard incidents."""

    down_domains: MonitorRecords
    unknown_domains: MonitorRecords
    degraded_signals: list[str]
    freshness: MonitorRecord
    e2e: MonitorRecord
    signals: MonitorRecord


def _freshness_incident(freshness: MonitorRecord) -> MonitorRecord | None:
    status = freshness.get("status")
    if status not in {"stale", "unknown"}:
        return None
    stale = status == "stale"
    return {
        "kind": "monitor_freshness",
        "severity": "critical" if stale else "warning",
        "title": "Monitoring state is stale" if stale else "Monitoring freshness is unavailable",
        "detail": "The minute monitor has not produced a current state snapshot.",
        "observed_at_ts": freshness.get("state_updated_at_ts"),
    }


def _domain_failure_detail(
    domain: MonitorRecord,
    failure_sources: list[str],
    *,
    telegram_enabled: bool,
) -> str:
    group_label = str(domain.get("group_label") or "Unconfigured")
    source_labels = {
        "primary": "page/readiness check",
        "api_contract": "API/service subcheck",
        "synthetic": "end-to-end transaction",
    }
    failing_checks = ", ".join(source_labels.get(source, source) for source in failure_sources)
    failure_streaks = [safe_int(monitor_mapping(domain.get("streaks")).get("fail")) or 0]
    if "api_contract" in failure_sources:
        failure_streaks.append(
            safe_int(monitor_mapping(domain.get("api_contract")).get("fail_streak")) or 0,
        )
    if "synthetic" in failure_sources:
        failure_streaks.append(
            safe_int(monitor_mapping(domain.get("synthetic")).get("fail_streak")) or 0,
        )
    failure_count = max(failure_streaks)
    detail = f"{group_label} · {failing_checks or 'health check'} is down after {failure_count} failing cycles."
    if telegram_enabled:
        return detail
    policy_reason = str(monitor_mapping(domain.get("alert_policy")).get("reason") or "").strip()
    detail += " Expected/dashboard-only status; no Telegram alert is routed."
    return f"{detail} {policy_reason}" if policy_reason else detail


def _down_incident(domain: MonitorRecord) -> MonitorRecord:
    last = monitor_mapping(domain.get("last"))
    policy = monitor_mapping(domain.get("alert_policy"))
    telegram_enabled = policy.get("telegram_enabled") is not False
    group_label = str(domain.get("group_label") or "Unconfigured")
    raw_failure_sources = last.get("failure_sources")
    source_values = raw_failure_sources if isinstance(raw_failure_sources, list) else []
    failure_sources = [str(source) for source in source_values]
    return {
        "kind": "domain_down",
        "severity": "critical" if telegram_enabled else "expected",
        "title": (
            f"{domain.get('domain')} is down"
            if telegram_enabled
            else f"{domain.get('domain')} is down — expected / dashboard only"
        ),
        "detail": _domain_failure_detail(
            domain,
            failure_sources,
            telegram_enabled=telegram_enabled,
        ),
        "domain": domain.get("domain"),
        "group": domain.get("group"),
        "group_label": group_label,
        "status_code": last.get("status_code"),
        "observed_at_ts": last.get("ts"),
        "telegram_alert": telegram_enabled,
        "expected": not telegram_enabled,
    }


def _unknown_incident(domain: MonitorRecord) -> MonitorRecord:
    policy = monitor_mapping(domain.get("alert_policy"))
    telegram_enabled = policy.get("telegram_enabled") is not False
    group_label = str(domain.get("group_label") or "Unconfigured")
    return {
        "kind": "domain_unknown",
        "severity": "warning" if telegram_enabled else "expected",
        "title": (
            f"{domain.get('domain')} has no current result"
            if telegram_enabled
            else f"{domain.get('domain')} has no current result — dashboard only"
        ),
        "detail": (
            f"{group_label} · the domain is enabled but has not produced a health result."
            + (" No Telegram alert is routed by policy." if not telegram_enabled else "")
        ),
        "domain": domain.get("domain"),
        "group": domain.get("group"),
        "group_label": group_label,
        "observed_at_ts": None,
        "telegram_alert": telegram_enabled,
        "expected": not telegram_enabled,
    }


def _signal_incident(signal: str, signals: MonitorRecord) -> MonitorRecord:
    signal_state = monitor_mapping(signals.get(signal))
    failure_count = safe_int(signal_state.get("fail_streak"))
    detail = "The latest debounced global signal is not healthy."
    if failure_count is not None:
        detail = f"The signal has failed {failure_count:,} consecutive monitor cycles."
    return {
        "kind": "signal_degraded",
        "severity": "warning",
        "title": f"{signal_display_name(signal)} is degraded",
        "detail": detail,
        "signal": signal,
        "observed_at_ts": signal_state.get("observed_at_ts"),
    }


def _e2e_incidents(e2e: MonitorRecord) -> MonitorRecords:
    problems = monitor_records(e2e.get("problems"))
    return [
        {
            "kind": "e2e_failure",
            "severity": "warning",
            "title": f"E2E: {problem.get('test_name')}",
            "detail": (
                f"{problem.get('base_url')} · "
                f"{safe_int(problem.get('fail_streak')) or 0} effective failures"
            ),
            "test_id": problem.get("test_id"),
            "observed_at_ts": problem.get("last_finished_at_ts"),
        }
        for problem in problems
    ]


def build_incidents(context: IncidentContext) -> MonitorRecords:
    """Return current operator incidents in deterministic priority order."""
    incidents: MonitorRecords = []
    freshness_incident = _freshness_incident(context.freshness)
    if freshness_incident is not None:
        incidents.append(freshness_incident)
    incidents.extend(_down_incident(domain) for domain in context.down_domains)
    incidents.extend(_unknown_incident(domain) for domain in context.unknown_domains)
    incidents.extend(_signal_incident(signal, context.signals) for signal in context.degraded_signals)
    incidents.extend(_e2e_incidents(context.e2e))
    return incidents
