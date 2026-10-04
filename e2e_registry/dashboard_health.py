# Copyright (c) 2026 PitchAI. All rights reserved.
"""Dashboard freshness, service grouping and rolling-day health calculations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain_checks.cycle_values import required_int

from .dashboard_inventory import normalize_domain_groups
from .dashboard_records import object_or_empty, required_object
from .dashboard_values import safe_int, safe_timestamp

if TYPE_CHECKING:
    from .dashboard_data import MonitorData
    from .dashboard_records import Record


def event_kind_is_problem(kind: str) -> bool:
    """Recognize the existing failure suffixes.

    Returns:
        Whether the normalized event kind carries a problem suffix.
    """
    normalized = str(kind or "").strip().lower()
    return normalized.endswith(("_down", "_degraded", "_failed", "_failure", "_error", "_unhealthy"))


def event_kind_is_recovery(kind: str) -> bool:
    """Recognize the existing recovery suffixes without changing incident state.

    Returns:
        Whether the normalized event kind carries a recovery suffix.
    """
    normalized = str(kind or "").strip().lower()
    return normalized.endswith(("_up", "_recovered", "_healthy"))


def summarize_freshness(*, data: MonitorData, now_ts: float, history_max_ts: float | None) -> Record:
    """Prefer the persisted update time, then the original history boundary.

    Returns:
        Unknown when both sources are absent; otherwise the original age policy.
    """
    updated_at = safe_timestamp((data.state or {}).get("updated_at"))
    source = "state.updated_at"
    if updated_at is None:
        updated_at = history_max_ts
        source = "history.max_ts" if history_max_ts is not None else "unavailable"
    interval = safe_int((data.config or {}).get("interval_seconds"))
    if interval is None or interval <= 0:
        interval = 60
    stale_after = max(180, interval * 3)
    age = max(0.0, float(now_ts) - updated_at) if updated_at is not None else None
    status = "unknown" if age is None else ("fresh" if age <= stale_after else "stale")
    return {
        "status": status, "state_updated_at_ts": updated_at, "age_seconds": age,
        "interval_seconds": interval, "stale_after_seconds": stale_after, "source": source,
    }


def summarize_service_health(domains: list[Record]) -> dict[str, int]:
    """Keep disabled, unknown and policy-expected failures distinct.

    Returns:
        The original seven service counts.
    """
    enabled = [domain for domain in domains if not bool(domain.get("disabled"))]
    down = [domain for domain in enabled if required_object(domain.get("last") or {}).get("ok") is False]
    unknown = [domain for domain in enabled if required_object(domain.get("last") or {}).get("ok") is None]
    expected = [domain for domain in down
                if required_object(domain.get("alert_policy") or {}).get("telegram_enabled") is False]
    return {
        "enabled": len(enabled), "healthy": len(enabled) - len(down) - len(unknown), "down": len(down),
        "alertable_down": len(down) - len(expected), "expected_down": len(expected), "unknown": len(unknown),
        "disabled": len(domains) - len(enabled),
    }


def summarize_domain_groups(*, domains: list[Record], config: Record) -> list[Record]:
    """Preserve configured and inferred group order and attention precedence.

    Returns:
        Populated groups sorted by their original numeric order and label.
    """
    configured = normalize_domain_groups(config.get("domain_groups"))
    definitions = {str(group["id"]): dict(group) for group in configured}
    for domain in domains:
        group_id = str(domain.get("group") or "unconfigured")
        _ = definitions.setdefault(group_id, {
            "id": group_id,
            "label": str(domain.get("group_label") or group_id.replace("-", " ").title()),
            "description": domain.get("group_description"), "order": domain.get("group_order") or 9999,
        })
    summaries: list[Record] = []
    for group_id, definition in definitions.items():
        members = [domain for domain in domains if str(domain.get("group") or "unconfigured") == group_id]
        if not members:
            continue
        health = summarize_service_health(members)
        status = "healthy"
        precedence = (("alertable_down", "attention"), ("expected_down", "expected"), ("unknown", "unknown"))
        for count, candidate in precedence:
            if health[count]:
                status = candidate
                break
        summaries.append({**definition, **health, "total": len(members), "status": status})
    return sorted(summaries, key=lambda group: (
        required_int(group.get("order") or 9999), str(group.get("label") or "").lower(),
    ))


def summarize_daily_status(
    *, domains: list[Record], events: list[Record], open_problem_count: int, now_ts: float,
) -> Record:
    """Count the inclusive rolling day without renewing timestamps or closing incidents.

    Returns:
        Availability from enabled observations and counts from retained events.
    """
    observations, successful = _daily_observations(domains)
    daily_events: list[Record] = []
    for event in events:
        timestamp = safe_timestamp(event.get("ts"))
        if timestamp is not None and float(now_ts) - 86400.0 <= timestamp <= float(now_ts):
            daily_events.append(event)
    problems = [event for event in daily_events if event_kind_is_problem(str(event.get("kind") or ""))]
    recoveries = [event for event in daily_events if event_kind_is_recovery(str(event.get("kind") or ""))]
    latest = None
    for event in daily_events:
        timestamp = safe_timestamp(event.get("ts"))
        if timestamp is not None:
            latest = timestamp if latest is None else max(latest, timestamp)
    status = "unknown" if observations == 0 else ("attention" if open_problem_count > 0 else "healthy")
    return {
        "period_seconds": 86400, "status": status, "observations": observations,
        "successful_observations": successful,
        "availability_pct": (successful / observations) * 100.0 if observations > 0 else None,
        "problem_events": len(problems), "recoveries": len(recoveries), "latest_event_at_ts": latest,
    }


def _daily_observations(domains: list[Record]) -> tuple[int, int]:
    observations = 0
    successful = 0
    for domain in domains:
        if bool(domain.get("disabled")):
            continue
        availability = object_or_empty(domain.get("availability_24h"))
        observations += safe_int(availability.get("total")) or 0
        successful += safe_int(availability.get("ok")) or 0
    return observations, successful
