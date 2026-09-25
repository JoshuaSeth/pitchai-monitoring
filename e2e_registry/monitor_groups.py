# Copyright (c) 2026 PitchAI. All rights reserved.
"""Domain-group and aggregate service-health summaries."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from e2e_registry.monitor_inventory import normalize_domain_groups
from e2e_registry.monitor_values import safe_int

if TYPE_CHECKING:
    from e2e_registry.monitor_types import MonitorRecord, MonitorRecords


def _last_status(domain: MonitorRecord) -> bool | None:
    last = domain.get("last")
    if not isinstance(last, dict):
        return None
    status = last.get("ok")
    return status if isinstance(status, bool) else None


def service_health(domains: MonitorRecords) -> MonitorRecord:
    """Return aggregate enabled, healthy, down, and policy-aware counts."""
    enabled = [domain for domain in domains if not bool(domain.get("disabled"))]
    down = [domain for domain in enabled if _last_status(domain) is False]
    unknown = [domain for domain in enabled if _last_status(domain) is None]
    domains_with_policy = (domain for domain in down if isinstance(domain.get("alert_policy"), dict))
    expected_down: MonitorRecords = []
    for domain in domains_with_policy:
        policy = cast("MonitorRecord", domain["alert_policy"])
        if policy.get("telegram_enabled") is False:
            expected_down.append(domain)
    return {
        "enabled": len(enabled),
        "healthy": len(enabled) - len(down) - len(unknown),
        "down": len(down),
        "alertable_down": len(down) - len(expected_down),
        "expected_down": len(expected_down),
        "unknown": len(unknown),
        "disabled": len(domains) - len(enabled),
    }


def _group_status(health: MonitorRecord) -> str:
    if health.get("alertable_down"):
        return "attention"
    if health.get("expected_down"):
        return "expected"
    if health.get("unknown"):
        return "unknown"
    return "healthy"


def summarize_domain_groups(*, domains: MonitorRecords, config: MonitorRecord) -> MonitorRecords:
    """Return policy-aware health totals for configured and inferred groups."""
    configured = normalize_domain_groups(config.get("domain_groups"))
    definitions = {str(group["id"]): dict(group) for group in configured}
    for domain in domains:
        group_id = str(domain.get("group") or "unconfigured")
        definitions.setdefault(
            group_id,
            {
                "id": group_id,
                "label": str(domain.get("group_label") or group_id.replace("-", " ").title()),
                "description": domain.get("group_description"),
                "order": domain.get("group_order") or 9999,
            },
        )
    summaries: MonitorRecords = []
    for group_id, definition in definitions.items():
        members = [domain for domain in domains if str(domain.get("group") or "unconfigured") == group_id]
        if not members:
            continue
        health = service_health(members)
        summaries.append({**definition, **health, "total": len(members), "status": _group_status(health)})
    return sorted(
        summaries,
        key=lambda group: (safe_int(group.get("order")) or 9999, str(group.get("label") or "").lower()),
    )
