# Copyright (c) 2026 PitchAI. All rights reserved.
"""Production-shaped data for monitoring dashboard inventory tests."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from domain_checks.main import load_config
from e2e_registry.models import require_json_object
from e2e_registry.monitor_dashboard import MonitorData, build_dashboard_summary

if TYPE_CHECKING:
    from e2e_registry.models import JsonObject
    from e2e_registry.monitor_types import MonitorRecord

_EXPECTED_ACTIVE_DOMAINS = 58
_EXPECTED_GROUPS = 14


def production_summary(now: float) -> JsonObject:
    """Build and validate a dashboard summary from production inventory.

    Returns:
        A production-shaped dashboard summary.

    Raises:
        AssertionError: If the inventory counts violate the production contract.
        TypeError: If the production domain configuration is not a list.
    """
    config_path = Path(__file__).resolve().parents[1] / "domain_checks" / "config.yaml"
    config = load_config(config_path)
    raw_domains = config.get("domains")
    if not isinstance(raw_domains, list):
        message = "production monitor config domains must be a list"
        raise TypeError(message)
    domain_names: list[str] = []
    for raw_entry in raw_domains:
        if not isinstance(raw_entry, dict):
            message = "production domain entries must be objects"
            raise TypeError(message)
        domain = raw_entry.get("domain")
        if not isinstance(domain, str) or not domain.strip():
            message = "production domain name must be non-empty text"
            raise TypeError(message)
        domain_names.append(domain)
    state: MonitorRecord = {
        "updated_at": now,
        "last_ok": {
            domain: domain != "agentcloud.pitchai.net" for domain in domain_names
        },
        "fail_streak": {
            domain: 3 if domain == "agentcloud.pitchai.net" else 0
            for domain in domain_names
        },
        "success_streak": {
            domain: 0 if domain == "agentcloud.pitchai.net" else 3
            for domain in domain_names
        },
        "history": {
            domain: (
                [[now - 60, False, 100.0, 250.0, 502], [now, False, 90.0, 230.0, 502]]
                if domain == "agentcloud.pitchai.net"
                else [
                    [now - 60, True, 100.0, 250.0, 200],
                    [now, True, 90.0, 230.0, 200],
                ]
            )
            for domain in domain_names
        },
    }
    summary = cast(
        "JsonObject",
        build_dashboard_summary(
            data=MonitorData(
                state=state,
                config=cast("MonitorRecord", config),
                state_path="/monitor/state.json",
                config_path=str(config_path),
                loaded_at_ts=now,
                state_error=None,
            ),
            now_ts=now,
            e2e_status_summary=None,
            e2e_dispatch_runs=[],
        ),
    )
    inventory = require_json_object(
        summary.get("inventory"), label="production inventory summary",
    )
    active_domains = inventory.get("active_domains")
    if active_domains != _EXPECTED_ACTIVE_DOMAINS:
        message = f"production inventory must contain 58 active domains: {active_domains!r}"
        raise AssertionError(message)
    groups = inventory.get("groups")
    if groups != _EXPECTED_GROUPS:
        message = f"production inventory must contain 14 groups: {groups!r}"
        raise AssertionError(message)
    return summary
