# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build the existing display incidents; no event emission or acknowledgement."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict, Unpack

from domain_checks.cycle_values import required_int

from .dashboard_records import iterable_values, object_or_empty, required_object
from .dashboard_signals import signal_display_name
from .dashboard_values import safe_int

if TYPE_CHECKING:
    from .dashboard_records import Record

_SUBCHECK_NAMES = ("api_contract", "synthetic")


class IncidentInputs(TypedDict):
    """Named inputs to the retained incident-building entry point."""

    down_domains: list[Record]
    unknown_domains: list[Record]
    degraded_signals: list[str]
    freshness: Record
    e2e: Record
    signals: Record


def _down_incident(domain: Record) -> Record:
    last = object_or_empty(domain.get("last"))
    policy = object_or_empty(domain.get("alert_policy"))
    telegram_enabled = policy.get("telegram_enabled") is not False
    policy_reason = str(policy.get("reason") or "").strip()
    group_label = str(domain.get("group_label") or "Unconfigured")
    sources = iterable_values(last.get("failure_sources") or [])
    failure_sources = [str(source) for source in sources]
    labels = {"primary": "page/readiness check", "api_contract": "API/service subcheck",
              "synthetic": "end-to-end transaction"}
    failing_checks = ", ".join(labels.get(source, source) for source in failure_sources)
    streaks = [required_int(required_object(domain.get("streaks") or {}).get("fail", 0))]
    failed_subchecks = [source for source in _SUBCHECK_NAMES if source in failure_sources]
    streaks.extend(required_int(required_object(domain.get(source) or {}).get("fail_streak") or 0)
                   for source in failed_subchecks)
    detail = f"{group_label} · {failing_checks or 'health check'} is down after {max(streaks)} failing cycles."
    if not telegram_enabled:
        detail += " Expected/dashboard-only status; no Telegram alert is routed."
        if policy_reason:
            detail += f" {policy_reason}"
    title = f"{domain.get('domain')} is down"
    if not telegram_enabled:
        title += " — expected / dashboard only"
    return {
        "kind": "domain_down", "severity": "critical" if telegram_enabled else "expected",
        "title": title, "detail": detail, "domain": domain.get("domain"), "group": domain.get("group"),
        "group_label": group_label, "status_code": last.get("status_code"), "observed_at_ts": last.get("ts"),
        "telegram_alert": telegram_enabled, "expected": not telegram_enabled,
    }


def _unknown_incident(domain: Record) -> Record:
    group_label = str(domain.get("group_label") or "Unconfigured")
    telegram_enabled = object_or_empty(domain.get("alert_policy")).get("telegram_enabled") is not False
    title = f"{domain.get('domain')} has no current result"
    detail = f"{group_label} · the domain is enabled but has not produced a health result."
    if not telegram_enabled:
        title += " — dashboard only"
        detail += " No Telegram alert is routed by policy."
    return {
        "kind": "domain_unknown", "severity": "warning" if telegram_enabled else "expected",
        "title": title, "detail": detail, "domain": domain.get("domain"), "group": domain.get("group"),
        "group_label": group_label, "observed_at_ts": None,
        "telegram_alert": telegram_enabled, "expected": not telegram_enabled,
    }


def build_incidents(**inputs: Unpack[IncidentInputs]) -> list[Record]:
    """Retain freshness/domain/signal/E2E ordering and display-only policy text.

    Returns:
        Local display descriptions without sending or changing source incidents.

    Malformed E2E values retain the original iteration/mapping failures at
    the typed persisted-value boundary.
    """
    freshness = inputs["freshness"]
    incidents: list[Record] = []
    if freshness.get("status") in {"stale", "unknown"}:
        stale = freshness.get("status") == "stale"
        incidents.append({
            "kind": "monitor_freshness", "severity": "critical" if stale else "warning",
            "title": "Monitoring state is stale" if stale else "Monitoring freshness is unavailable",
            "detail": "The minute monitor has not produced a current state snapshot.",
            "observed_at_ts": freshness.get("state_updated_at_ts"),
        })
    incidents.extend(_down_incident(domain) for domain in inputs["down_domains"])
    incidents.extend(_unknown_incident(domain) for domain in inputs["unknown_domains"])
    for signal in inputs["degraded_signals"]:
        state = object_or_empty(inputs["signals"].get(signal))
        count = safe_int(state.get("fail_streak"))
        detail = "The latest debounced global signal is not healthy."
        if count is not None:
            detail = f"The signal has failed {count:,} consecutive monitor cycles."
        incidents.append({
            "kind": "signal_degraded", "severity": "warning", "title": f"{signal_display_name(signal)} is degraded",
            "detail": detail, "signal": signal, "observed_at_ts": state.get("observed_at_ts"),
        })
    problems = iterable_values(inputs["e2e"].get("problems") or [])
    for raw in problems:
        problem = required_object(raw)
        count = required_int(problem.get("fail_streak") or 0)
        incidents.append({
            "kind": "e2e_failure", "severity": "warning", "title": f"E2E: {problem.get('test_name')}",
            "detail": f"{problem.get('base_url')} · {count} effective failures",
            "test_id": problem.get("test_id"), "observed_at_ts": problem.get("last_finished_at_ts"),
        })
    return incidents
