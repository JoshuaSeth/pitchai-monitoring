# Copyright (c) 2026 PitchAI. All rights reserved.
"""Normalize display inventory while preserving configured order and policy."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, cast

from domain_checks.cycle_values import required_int
from domain_checks.inventory import parse_domain_alert_policy

from .disablement import parse_disabled_until

if TYPE_CHECKING:
    from domain_checks.config_values import ConfigValue

type DisplayEntry = dict[str, ConfigValue]


def _domain_entry(entry: ConfigValue, index: int) -> DisplayEntry | None:
    if isinstance(entry, str):
        domain = entry.strip()
        if not domain:
            return None
        return {
            "domain": domain, "label": domain, "group": "ungrouped", "environment": "unspecified",
            "kind": "application", "disabled": False, "disabled_reason": None, "disabled_until_ts": None,
            "alert_policy": cast("ConfigValue", parse_domain_alert_policy(entry).to_dashboard_dict()),
        }
    if not isinstance(entry, dict):
        return None
    domain = str(entry.get("domain") or "").strip()
    if not domain:
        return None
    disabled = bool(entry.get("disabled")) or (entry.get("enabled") is False)
    policy = parse_domain_alert_policy(entry, path=f"domains[{index}]")
    until = entry.get("disabled_until")
    if not isinstance(until, (str, int, float, type(None))):
        until = str(until or "")
    return {
        "domain": domain,
        "label": str(entry.get("label") or domain).strip(),
        "group": str(entry.get("group") or "ungrouped").strip(),
        "environment": str(entry.get("environment") or "unspecified").strip(),
        "kind": str(entry.get("kind") or "application").strip(),
        "disabled": disabled,
        "disabled_reason": str(entry.get("disabled_reason") or "").strip() or None,
        "disabled_until_ts": parse_disabled_until(until),
        "alert_policy": cast("ConfigValue", policy.to_dashboard_dict()),
    }


def normalize_domain_entries(domains_cfg: ConfigValue) -> list[DisplayEntry]:
    """Normalize all entries before deduplicating, retaining policy errors in duplicates.

    Returns:
        The first nonempty entry for each domain, in configured order.
    """
    if not isinstance(domains_cfg, list):
        return []
    entries: list[DisplayEntry] = []
    for index, raw in enumerate(domains_cfg):
        entry = _domain_entry(raw, index)
        if entry is not None:
            entries.append(entry)
    seen: set[str] = set()
    deduplicated: list[DisplayEntry] = []
    for entry in entries:
        domain = str(entry.get("domain") or "").strip()
        if domain and domain not in seen:
            seen.add(domain)
            deduplicated.append(entry)
    return deduplicated


def normalize_domain_groups(groups_cfg: ConfigValue) -> list[DisplayEntry]:
    """Retain group fallback labels and numeric order, including error propagation.

    Returns:
        Valid mapping entries sorted by order then lowercase label.
    """
    if not isinstance(groups_cfg, dict):
        return []
    groups: list[DisplayEntry] = []
    for group_id, raw in groups_cfg.items():
        cleaned_id = str(group_id or "").strip()
        if not cleaned_id or not isinstance(raw, dict):
            continue
        order = 1000
        with suppress(TypeError, ValueError):
            order = required_int(raw.get("order", 1000))
        groups.append({
            "id": cleaned_id,
            "label": str(raw.get("label") or cleaned_id.replace("-", " ").title()).strip(),
            "description": str(raw.get("description") or "").strip() or None,
            "order": order,
        })
    return sorted(groups, key=lambda group: (required_int(group["order"]), str(group["label"]).lower()))
