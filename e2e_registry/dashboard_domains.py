# Copyright (c) 2026 PitchAI. All rights reserved.
"""Configured-domain summaries without reviving retired history entries."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, cast

from domain_checks.cycle_values import required_int

from .dashboard_domain_metrics import day_metrics, effective_observation, primary_observation, subcheck_summaries
from .dashboard_inventory import normalize_domain_entries, normalize_domain_groups
from .dashboard_records import object_or_empty, required_object

if TYPE_CHECKING:
    from domain_checks.event_bus_delivery import JsonObject
    from domain_checks.history import Sample

    from .dashboard_data import MonitorData
    from .dashboard_records import Record


class DomainContext(NamedTuple):
    """Read-only source references needed for each configured domain."""

    state: JsonObject
    performance: Record
    groups: dict[str, Record]
    now_ts: float


def summarize_domains(*, data: MonitorData, now_ts: float) -> list[Record]:
    """Combine primary/subcheck results in authoritative configured inventory order.

    Returns:
        Display records retaining disabled policy, history and individual failure sources.
    """
    state = data.state or {}
    histories = object_or_empty(state.get("history"))
    entries = normalize_domain_entries((data.config or {}).get("domains"))
    groups = normalize_domain_groups((data.config or {}).get("domain_groups"))
    groups_by_id = {str(group["id"]): group for group in groups}
    # Preserve evaluation of known state even when configured inventory wins.
    known_domains = set(histories) | set(required_object(state.get("last_ok") or {}, operation="keys"))
    ordered = [str(entry.get("domain") or "") for entry in entries]
    all_domains = [domain for domain in ordered if domain] if entries else sorted(known_domains)
    config_map = {str(entry.get("domain") or ""): entry for entry in entries}
    context = DomainContext(state, object_or_empty((data.config or {}).get("performance")), groups_by_id, now_ts)
    output: list[Record] = []
    for domain in all_domains:
        items = cast("list[Sample]", histories.get(domain) or [])
        output.append(_domain_summary(domain, items, config_map.get(domain) or {}, context))
    return output


def _domain_summary(domain: str, items: list[Sample], info: Record, context: DomainContext) -> Record:
    primary = primary_observation(items, state=context.state, domain=domain)
    metrics = day_metrics(items, performance=context.performance, now_ts=context.now_ts)
    last, subchecks = effective_observation(primary, state=context.state, domain=domain)
    group_id = str(info.get("group") or "unconfigured")
    group = context.groups.get(group_id) or {
        "id": group_id, "label": group_id.replace("-", " ").title(), "description": None, "order": 9999,
    }
    return {
        "domain": domain, "label": str(info.get("label") or domain), "group": group_id,
        "group_label": group.get("label"), "group_description": group.get("description"),
        "group_order": group.get("order"), "environment": str(info.get("environment") or "unspecified"),
        "kind": str(info.get("kind") or "application"), "disabled": bool(info.get("disabled", False)),
        "disabled_reason": info.get("disabled_reason"), "disabled_until_ts": info.get("disabled_until_ts"),
        "alert_policy": info.get("alert_policy"), "last": last,
        "streaks": {
            "fail": required_int(required_object(context.state.get("fail_streak") or {}).get(domain, 0)),
            "success": required_int(required_object(context.state.get("success_streak") or {}).get(domain, 0)),
        },
        **metrics,
        **subcheck_summaries(subchecks, state=context.state, domain=domain),
    }
