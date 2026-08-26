# Copyright (c) 2026 PitchAI. All rights reserved.
"""Exercise the database dependency state and alert policy contracts."""

from __future__ import annotations

import math

import pytest

from domain_checks.database_dependencies.configuration import load_settings
from domain_checks.monitoring_contracts.json_types import float_value, object_list
from monitoring_test_support.database_dependency import (
    ROOT,
    DefinitionOptions,
    cycle,
    definition,
    observation,
)
from monitoring_test_support.expectations import present

_EXPECTED_MAX_PARALLEL_PROBES = 4
_EXPECTED_GROUP_MEMBERS = 2
_FAILURE_STARTED_AT = 200.0
_FAILURE_LATENCY_MS = 18.5
_SUCCESS_LATENCY_MS = 7.25


def test_production_configuration_has_explicit_db_routes_and_alert_policy() -> None:
    """Require exact database routing, grant checks, and alert policy."""
    settings = load_settings(ROOT / "domain_checks/config.yaml")

    if settings.max_parallel_probes != _EXPECTED_MAX_PARALLEL_PROBES:
        pytest.fail("database probe concurrency changed")
    expected_policies = {
        "deplanbook-blue-green",
        "dft-blue-green",
        "orthoparse-blue-green",
    }
    if {policy.policy_id for policy in settings.routing_policies} != expected_policies:
        pytest.fail("production routing policies changed")
    rules = {rule.rule_id: rule for rule in settings.rules}
    expected_dft_relations = ("auth_users", "formative_flows", "system_status_banners")
    if rules["dft-web-blue"].relation_checks != expected_dft_relations:
        pytest.fail("DFT relation-grant coverage changed")
    if rules["orthoparse-web-green"].engine_attr != "web_app.db:get_engine":
        pytest.fail("Orthoparse engine probe changed")
    if rules["deplanbook-green"].connection_mode != "asyncpg_url":
        pytest.fail("DePlanBook connection mode changed")
    if rules["potaito-model-lab"].telegram_enabled is not False:
        pytest.fail("intentionally quiet Potaito surface became alertable")
    if rules["discovered-production"].container_pattern.pattern != ".*":
        pytest.fail("catch-all database ownership policy is missing")


def test_group_alert_is_debounced_deduplicated_and_recovers_only_when_all_members_do() -> None:
    """Debounce one group alert and recover only after every member succeeds."""
    web = definition("web")
    worker = definition("worker")
    definitions = [web, worker]
    state = cycle(
        definitions,
        [observation(web, at=100.0, ok=False), observation(worker, at=100.0, ok=False)],
        at=100.0,
    )
    if state["status"] != "degraded":
        pytest.fail("first failure skipped debounce")
    if state["pending_alerts"] != []:
        pytest.fail("first failure queued an alert")

    state = cycle(
        definitions,
        [observation(web, at=200.0, ok=False), observation(worker, at=200.0, ok=False)],
        previous=state,
        at=200.0,
    )
    pending = object_list(state.get("pending_alerts"))
    if len(pending) != 1:
        pytest.fail("group failure did not deduplicate to one alert")
    if pending[0]["alert_group"] != "app-database":
        pytest.fail("alert used the wrong group")
    if len(object_list(pending[0].get("members"))) != _EXPECTED_GROUP_MEMBERS:
        pytest.fail("group alert omitted a failing dependency")
    if state["status"] != "down":
        pytest.fail("debounced group failure was not down")

    state = cycle(
        definitions,
        [observation(web, at=300.0, ok=True), observation(worker, at=300.0, ok=False)],
        previous=state,
        at=300.0,
    )
    if len(object_list(state.get("pending_alerts"))) != 1:
        pytest.fail("pending alert was duplicated")
    if object_list(state.get("alert_groups"))[0]["status"] != "down":
        pytest.fail("group recovered too early")

    state = cycle(
        definitions,
        [observation(web, at=400.0, ok=True), observation(worker, at=400.0, ok=True)],
        previous=state,
        at=400.0,
    )
    if object_list(state.get("alert_groups"))[0]["status"] != "down":
        pytest.fail("recovery skipped debounce")

    state = cycle(
        definitions,
        [observation(web, at=500.0, ok=True), observation(worker, at=500.0, ok=True)],
        previous=state,
        at=500.0,
    )
    if object_list(state.get("alert_groups"))[0]["status"] != "healthy":
        pytest.fail("group did not recover")
    if len(object_list(state.get("pending_alerts"))) != 1:
        pytest.fail("recovery changed pending delivery")


def test_inactive_route_and_probe_infrastructure_failure_never_page() -> None:
    """Keep inactive slots and monitor-boundary failures out of Telegram."""
    standby = definition(
        "standby",
        options=DefinitionOptions(traffic_state="inactive", route_eligible=False),
    )
    active = definition("active")
    state = cycle(
        [standby, active],
        [
            observation(standby, at=100.0, ok=False),
            observation(
                active,
                at=100.0,
                ok=False,
                failure_class="probe_runtime_missing",
            ),
        ],
        at=100.0,
    )
    state = cycle(
        [standby, active],
        [
            observation(standby, at=200.0, ok=False),
            observation(
                active,
                at=200.0,
                ok=False,
                failure_class="probe_runtime_missing",
            ),
        ],
        previous=state,
        at=200.0,
    )

    if state["status"] != "degraded":
        pytest.fail("non-alertable failures marked the state down")
    if state["pending_alerts"] != []:
        pytest.fail("non-alertable failures queued Telegram")
    dependency_items = object_list(state.get("dependencies"))
    items = {item["dependency_id"]: item for item in dependency_items}
    if items["standby"]["telegram_suppression_reason"] != "inactive_slot":
        pytest.fail("inactive route lacked its suppression reason")
    if items["active"]["telegram_suppression_reason"] != "monitoring_boundary_failure":
        pytest.fail("probe boundary failure lacked its suppression reason")


def test_stale_credential_signal_and_success_latency_are_retained() -> None:
    """Retain last success evidence and expose a post-success stale credential."""
    probe = definition("web")
    state = cycle(
        [probe],
        [observation(probe, at=100.0, ok=True, latency_ms=_SUCCESS_LATENCY_MS)],
        at=100.0,
    )
    state = cycle(
        [probe],
        [
            observation(
                probe,
                at=_FAILURE_STARTED_AT,
                ok=False,
                latency_ms=_FAILURE_LATENCY_MS,
            ),
        ],
        previous=state,
        at=_FAILURE_STARTED_AT,
    )
    item = object_list(state.get("dependencies"))[0]

    if item["credential_state"] != "stale_or_revoked_after_last_success":
        pytest.fail("stale credential signal was not exposed")
    success_latency = present(
        float_value(item.get("last_success_latency_ms")),
        label="success latency is missing",
    )
    failure_latency = present(
        float_value(item.get("last_failure_latency_ms")),
        label="failure latency is missing",
    )
    failure_started = present(
        float_value(item.get("failure_started_at_ts")),
        label="failure start is missing",
    )
    if not math.isclose(
        success_latency,
        _SUCCESS_LATENCY_MS,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        pytest.fail(
            f"success latency changed: expected {_SUCCESS_LATENCY_MS!r}, got {success_latency!r}",
        )
    if not math.isclose(
        failure_latency,
        _FAILURE_LATENCY_MS,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        pytest.fail(
            f"failure latency changed: expected {_FAILURE_LATENCY_MS!r}, got {failure_latency!r}",
        )
    if not math.isclose(
        failure_started,
        _FAILURE_STARTED_AT,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        pytest.fail(
            f"failure start changed: expected {_FAILURE_STARTED_AT!r}, got {failure_started!r}",
        )
