# Copyright (c) 2026 PitchAI. All rights reserved.
"""Prove critical app routing, suppression, cooldown, and recovery."""

from __future__ import annotations

from itertools import chain
from typing import TYPE_CHECKING, cast

from .domain_event_policy import domain_incident_policies
from .domain_event_state import empty_domain_producer_state
from .inventory import production_config
from .json_types import json_object, text_value, value_list
from .production_event_reducer import ProductionReductionContext, reduce_production_events
from .testing_runtime import pytest

if TYPE_CHECKING:
    from .domain_event_models import DomainProducerState, DomainReduction
    from .json_types import JsonInput, JsonObject

_EVENT_TIME = 1_787_860_800.0
_REESCALATION_SECONDS = 1_861.0
_CHANGED_FAILURE_COUNT = 3


def _reduce(
    source: JsonObject,
    *,
    now: float,
    retained: DomainProducerState | None = None,
    initial_bootstrap: bool = True,
) -> DomainReduction:
    config = production_config()
    return reduce_production_events(
        context=ProductionReductionContext(
            policies=domain_incident_policies(config),
            config=config,
            source_state=source,
            now=now,
            initial_bootstrap=initial_bootstrap,
        ),
        retained=retained or empty_domain_producer_state(),
    )


def _synthetic_failure(*, failures: int = 2) -> JsonObject:
    return json_object(
        cast(
            "JsonInput",
            {
                "last_ok": {"afasask.gzb.nl": True},
                "synthetic": {"last_ok": {"afasask.gzb.nl": False}},
                "proxy": {"last_ok": True},
                "events": [
                    {
                        "ts": _EVENT_TIME,
                        "kind": "synthetic_degraded",
                        "domain": "afasask.gzb.nl",
                        "failures": failures,
                        "telegram_alert": True,
                    },
                ],
            },
        ),
    )


def test_real_synthetic_failure_routes_complete_critical_incident() -> None:
    """Promote a debounced real transaction failure to its exact owner project."""
    reduction = _reduce(_synthetic_failure(), now=_EVENT_TIME + 10.0)
    if len(reduction.events) != 1 or reduction.events[0].kind != "production_failure":
        pytest.fail("real production transaction failure did not become one app incident")
    details = reduction.events[0].details
    required = {
        "domain",
        "owner_project",
        "incident_key",
        "incident_fingerprint",
        "target_environment",
        "expected_behavior",
        "failed_checks",
        "evidence",
        "logs_hint",
        "likely_fix_path",
        "outgoing_message_boundary",
    }
    if required - set(details):
        pytest.fail(f"production incident context is incomplete: {sorted(required - set(details))}")
    if details.get("owner_project") != "afasask":
        pytest.fail("AFASAsk production failure did not route to its registered project")
    if details.get("synthetic") is not False or details.get("critical") is not True:
        pytest.fail("real synthetic transaction failure was mistaken for a safe synthetic proof")


def test_suppressed_and_noisy_signals_never_enter_repair_dispatch() -> None:
    """Exclude dashboard-only, internal, container, SLO, and performance noise."""
    source = json_object(
        cast(
            "JsonInput",
            {
                "last_ok": {"theplanbook.pitchai.net": True},
                "synthetic": {"last_ok": {"theplanbook.pitchai.net": False}},
                "api_contract": {"last_ok": {"dispatch.pitchai.net": False}},
                "proxy": {"last_ok": True},
                "events": [
                    {
                        "ts": _EVENT_TIME,
                        "kind": "synthetic_degraded",
                        "domain": "theplanbook.pitchai.net",
                        "failures": 2,
                        "telegram_alert": False,
                    },
                    {
                        "ts": _EVENT_TIME,
                        "kind": "api_contract_degraded",
                        "domain": "dispatch.pitchai.net",
                        "failures": 1,
                        "telegram_alert": False,
                    },
                    {"ts": _EVENT_TIME, "kind": "container_health_degraded"},
                    {"ts": _EVENT_TIME, "kind": "performance_degraded"},
                    {"ts": _EVENT_TIME, "kind": "slo_degraded"},
                ],
            },
        ),
    )
    reduction = _reduce(source, now=_EVENT_TIME + 10.0)
    if reduction.events or any(key.startswith("production:") for key in reduction.state.incidents):
        pytest.fail("suppressed or non-surface degradation entered the repair-agent loop")


def test_proxy_failure_cools_down_reescalates_and_recovers() -> None:
    """Keep one global proxy lane quiet inside cooldown and reconcile recovery."""
    degraded = json_object(
        cast(
            "JsonInput",
            {
                "proxy": {"last_ok": False},
                "events": [
                    {
                        "ts": _EVENT_TIME,
                        "kind": "proxy_degraded",
                        "upstream_issues": 3,
                        "access_502_504_percent": 4.5,
                        "upstream_events": 7,
                    },
                ],
            },
        ),
    )
    first = _reduce(degraded, now=_EVENT_TIME + 10.0)
    quiet = _reduce(
        degraded,
        now=_EVENT_TIME + 100.0,
        retained=first.state,
        initial_bootstrap=False,
    )
    repeated = _reduce(
        degraded,
        now=_EVENT_TIME + 10.0 + _REESCALATION_SECONDS,
        retained=quiet.state,
        initial_bootstrap=False,
    )
    recovered = json_object(
        cast(
            "JsonInput",
            {
                "proxy": {"last_ok": True},
                "events": [
                    *value_list(degraded.get("events")),
                    {"ts": _EVENT_TIME + 2_000.0, "kind": "proxy_recovered"},
                ],
            },
        ),
    )
    final = _reduce(
        recovered,
        now=_EVENT_TIME + 2_000.0,
        retained=repeated.state,
        initial_bootstrap=False,
    )
    transitions = chain(first.events, quiet.events, repeated.events, final.events)
    kinds = [event.kind for event in transitions]
    if kinds != ["production_failure", "production_failure", "production_recovered"]:
        pytest.fail(f"production proxy transition order is wrong: {kinds}")
    first_details = first.events[0].details
    if first_details.get("owner_project") != "pitchai_infrastructure":
        pytest.fail("global proxy failure did not route to PitchAI infrastructure")
    if text_value(first_details.get("incident_key")) in final.state.incidents:
        pytest.fail("proxy recovery left an open producer incident")


def test_material_change_escalates_inside_cooldown() -> None:
    """Allow changed failure evidence through while suppressing exact duplicates."""
    first = _reduce(_synthetic_failure(failures=2), now=_EVENT_TIME + 10.0)
    changed_source = _synthetic_failure(failures=_CHANGED_FAILURE_COUNT)
    changed_source["events"] = [
        *value_list(changed_source.get("events")),
        {
            "ts": _EVENT_TIME + 30.0,
            "kind": "synthetic_degraded",
            "domain": "afasask.gzb.nl",
            "failures": _CHANGED_FAILURE_COUNT,
            "telegram_alert": True,
        },
    ]
    changed = _reduce(
        changed_source,
        now=_EVENT_TIME + 30.0,
        retained=first.state,
        initial_bootstrap=False,
    )
    if len(changed.events) != 1 or changed.events[0].details.get("failures") != _CHANGED_FAILURE_COUNT:
        pytest.fail("materially changed production evidence was suppressed by cooldown")
