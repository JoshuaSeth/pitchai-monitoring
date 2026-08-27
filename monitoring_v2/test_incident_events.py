# Copyright (c) 2026 PitchAI. All rights reserved.
"""Prove critical database incident transitions and durable delivery."""

from __future__ import annotations

import hashlib
from functools import partial
from typing import TYPE_CHECKING, cast

from httpx import MockTransport, Response

from .database_dependency import DefinitionOptions, cycle, definition, observation
from .event_bus_delivery import DatabaseEventBus
from .incident_events import database_transition_events
from .json_types import object_list, optional_object, text_value
from .testing_runtime import pytest

if TYPE_CHECKING:
    from httpx import Request

    from .testing_runtime import MonkeyPatch

_ACCEPTED_STATUS = 202


def _accepted(request: Request) -> Response:
    delivery_id = cast("str", request.headers.get("X-PitchAI-Monitoring-Delivery", ""))
    response_factory = partial(
        Response,
        _ACCEPTED_STATUS,
        request=request,
        json={"accepted": 1, "event_ids": [f"event-for-{delivery_id}"]},
    )
    return response_factory()


def _configure_event_bus(monkeypatch: MonkeyPatch) -> None:
    signing_key = hashlib.sha256(b"database-event-bus-test-key").hexdigest()
    monkeypatch.setenv(
        "PITCHAI_MONITORING_EVENT_BUS_URL",
        "https://pitchai.net/events-bus/webhooks/pitchai-monitoring",
    )
    monkeypatch.setenv("PITCHAI_MONITORING_EVENT_BUS_SECRET", signing_key)
    monkeypatch.setenv("PITCHAI_MONITORING_ENVIRONMENT", "production")
    monkeypatch.setenv("PITCHAI_MONITORING_INSTANCE", "pytest-database")


def test_database_transition_uses_the_telegram_debounce_and_recovery_policy() -> None:
    """Emit one alertable DOWN and one recovery only after debounce."""
    probe = definition("web")
    first_failure = cycle([probe], [observation(probe, at=100.0, ok=False)], at=100.0)
    if database_transition_events(previous={}, updated=first_failure):
        pytest.fail("first database failure bypassed debounce")

    down = cycle(
        [probe],
        [observation(probe, at=200.0, ok=False)],
        previous=first_failure,
        at=200.0,
    )
    opened_events = database_transition_events(previous=first_failure, updated=down)
    if len(opened_events) != 1:
        pytest.fail("debounced database failure did not emit exactly one event")
    opened = opened_events[0]
    if opened.kind != "database_down":
        pytest.fail("database failure emitted the wrong event kind")
    if opened.details.get("incident_key") != "database:app-database":
        pytest.fail("database failure used the wrong incident key")
    if opened.details.get("owner_project") != "Example":
        pytest.fail("database failure lost owner-project routing")
    if database_transition_events(previous=down, updated=down):
        pytest.fail("unchanged database failure emitted a duplicate event")

    first_success = cycle(
        [probe],
        [observation(probe, at=300.0, ok=True)],
        previous=down,
        at=300.0,
    )
    recovered = cycle(
        [probe],
        [observation(probe, at=400.0, ok=True)],
        previous=first_success,
        at=400.0,
    )
    recovery_events = database_transition_events(previous=first_success, updated=recovered)
    if len(recovery_events) != 1 or recovery_events[0].kind != "database_recovered":
        pytest.fail("debounced database recovery did not emit exactly one recovery")
    if recovery_events[0].details.get("incident_key") != opened.details.get("incident_key"):
        pytest.fail("database recovery did not resolve the original incident key")


def test_noncritical_database_surface_remains_suppressed() -> None:
    """Keep explicitly noncritical database surfaces out of agent dispatch."""
    quiet_probe = definition("quiet", options=DefinitionOptions(critical=False))
    first = cycle([quiet_probe], [observation(quiet_probe, at=100.0, ok=False)], at=100.0)
    down = cycle(
        [quiet_probe],
        [observation(quiet_probe, at=200.0, ok=False)],
        previous=first,
        at=200.0,
    )
    if database_transition_events(previous=first, updated=down):
        pytest.fail("noncritical database surface emitted a repair-agent event")


def test_database_outbox_checkpoints_then_delivers_the_immutable_event(
    monkeypatch: MonkeyPatch,
) -> None:
    """Stage the incident before checkpoint and remove it only after acceptance."""
    _configure_event_bus(monkeypatch)
    probe = definition("web")
    previous = cycle([probe], [observation(probe, at=100.0, ok=False)], at=100.0)
    updated = cycle(
        [probe],
        [observation(probe, at=200.0, ok=False)],
        previous=previous,
        at=200.0,
    )
    event_bus = DatabaseEventBus.from_state({})
    if event_bus is None:
        pytest.fail("configured database Events Bus was not loaded")
    staged = event_bus.staged_for_cycle(previous=previous, updated=updated)
    retained_entries = object_list(staged.state_value())
    if event_bus.pending_count != 0 or staged.pending_count != 1 or len(retained_entries) != 1:
        pytest.fail("database incident was not isolated in the staged outbox")
    payload = optional_object(retained_entries[0].get("payload"))
    delivery_id = text_value(payload.get("delivery_id"))
    if payload.get("event_kind") != "database_down" or not delivery_id:
        pytest.fail("staged database event envelope is incomplete")

    transport_factory = partial(MockTransport, _accepted)
    attempts = staged.flush(now=201.0, transport=transport_factory())
    if len(attempts) != 1 or not attempts[0].success:
        pytest.fail("database incident was not accepted by the Events Bus")
    if attempts[0].delivery_id != delivery_id:
        pytest.fail("database outbox changed the immutable delivery identity")
    if staged.entries:
        pytest.fail("database outbox did not acknowledge the accepted immutable event")
