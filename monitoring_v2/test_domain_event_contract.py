# Copyright (c) 2026 PitchAI. All rights reserved.
"""Prove canonical domain routing and the complete critical event contract."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from .domain_event_contract import domain_down_event
from .domain_event_policy import domain_incident_policies
from .domain_event_reducer import reduce_domain_events
from .domain_event_state import empty_domain_producer_state
from .inventory import production_config
from .json_types import json_object
from .testing_runtime import pytest

if TYPE_CHECKING:
    from .json_types import JsonInput

_EVENT_TIME = 1_787_860_800.0


def test_unimix_domains_have_customer_group_and_project_routing() -> None:
    """Keep both canonical Unimix routes alertable in their customer group."""
    policies = domain_incident_policies(production_config())
    for domain in ("unimixbrasil.com.br", "www.unimixbrasil.com.br"):
        policy = policies[domain]
        if policy.group != "unimix" or policy.group_label != "Unimix":
            pytest.fail(f"{domain} lost the Unimix customer grouping")
        if policy.owner_project != "pitchai_monitoring" or not policy.alertable:
            pytest.fail(f"{domain} lost safe fallback project routing")
        if policy.expected_final_host_suffix != "unimixbrasil.com.br":
            pytest.fail(f"{domain} lost canonical-host redirect acceptance")


def test_known_client_groups_route_to_registered_owner_projects() -> None:
    """Prefer exact registered project owners over the generic monitoring lane."""
    policies = domain_incident_policies(production_config())
    expected = {
        "aigenda.pitchai.net": "driestar",
        "skybuyfly.pitchai.net": "ai_price_crawler",
        "stable.skybuyfly.pitchai.net": "ai_price_crawler",
    }
    for domain, owner_project in expected.items():
        policy = policies[domain]
        if policy.owner_project != owner_project or not policy.alertable:
            pytest.fail(f"{domain} lost exact owner-project routing")


def test_domain_down_contract_is_actionable_and_sanitized() -> None:
    """Include repair context without propagating URL secrets or private evidence."""
    policy = domain_incident_policies(production_config())["unimixbrasil.com.br"]
    event = domain_down_event(
        policy,
        {
            "ts": _EVENT_TIME,
            "kind": "domain_down",
            "domain": policy.domain,
            "reason": "unexpected redirect https://unimixbrasil.com.br/?token=secret-value",
            "status_code": 503,
            "error": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456",
            "fail_streak": 2,
            "telegram_alert": True,
        },
        occurred_at=_EVENT_TIME,
        re_escalation=False,
    )
    details = event.details
    required = {
        "domain",
        "owner_project",
        "project_group",
        "incident_key",
        "incident_fingerprint",
        "severity",
        "target_environment",
        "expected_behavior",
        "failed_checks",
        "evidence",
        "dashboard_url",
        "artifact_links",
        "source_config_path",
        "repair_dispatch",
        "outgoing_message_boundary",
    }
    missing = sorted(required - set(details))
    if missing:
        pytest.fail(f"domain incident contract is incomplete: {missing}")
    encoded = json.dumps(details, sort_keys=True)
    if "secret-value" in encoded or "abcdefghijklmnopqrstuvwxyz123456" in encoded:
        pytest.fail("domain incident contract leaked sanitized evidence")
    if details.get("severity") != "critical" or details.get("synthetic") is not False:
        pytest.fail("real production failure lost strict critical routing fields")


def test_normal_canonical_behavior_and_suppressed_surfaces_emit_no_agent_event() -> None:
    """Avoid repair dispatch for healthy redirects and dashboard-only surfaces."""
    policies = domain_incident_policies(production_config())
    source = json_object(
        cast(
            "JsonInput",
            {
                "last_ok": {
                    "www.unimixbrasil.com.br": True,
                    "theplanbook.pitchai.net": False,
                },
                "events": [
                    {
                        "ts": _EVENT_TIME,
                        "kind": "domain_down",
                        "domain": "theplanbook.pitchai.net",
                        "reason": "dashboard-only alias unavailable",
                        "telegram_alert": False,
                    },
                ],
            },
        ),
    )
    reduction = reduce_domain_events(
        policies=policies,
        source_state=source,
        retained=empty_domain_producer_state(),
        now=_EVENT_TIME,
    )
    if reduction.events:
        pytest.fail("healthy canonical redirect or dashboard-only failure dispatched an agent")
    if reduction.state.incidents:
        pytest.fail("suppressed surface remained open in producer incident state")
