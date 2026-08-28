# Copyright (c) 2026 PitchAI. All rights reserved.
"""Prove durable domain/app routing, cooldown, re-escalation, and recovery."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from httpx import MockTransport, Response

from .domain_event_sidecar import run_cycle
from .domain_event_state import load_domain_producer_state
from .domain_event_test_support import (
    EVENT_TIME,
    REESCALATION_SECONDS,
    accepted_requests,
    configure_event_bus,
    domain_down_state,
    production_failure_state,
)
from .inventory import CONFIG_PATH
from .json_types import text_value, value_list
from .state_io import write_state
from .testing_runtime import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import Request

    from .json_types import JsonObject
    from .testing_runtime import MonkeyPatch


def _assert_single_delivery(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    *,
    source_state: JsonObject,
    expected_kind: str,
) -> None:
    configure_event_bus(monkeypatch)
    source_path = tmp_path / "source.json"
    state_path = tmp_path / "producer.json"
    write_state(source_path, source_state)
    captured: list[JsonObject] = []
    receipt = run_cycle(
        config_path=CONFIG_PATH,
        source_path=source_path,
        state_path=state_path,
        now=EVENT_TIME + 10.0,
        transport=accepted_requests(captured),
    )
    retained = load_domain_producer_state(state_path)
    if receipt.staged_count != 1 or receipt.delivered_count != 1 or receipt.pending_count != 0:
        pytest.fail(f"critical incident did not drain exactly once: {receipt}")
    if len(captured) != 1 or captured[0].get("event_kind") != expected_kind:
        pytest.fail("sidecar delivered the wrong immutable event")
    delivery_id = text_value(captured[0].get("delivery_id"))
    if retained.last_delivery_id != delivery_id:
        pytest.fail("producer did not retain the receiver-dedupe delivery identity")
    if retained.last_receiver_event_id != f"domain-event-for-{delivery_id}":
        pytest.fail("producer did not retain the Events Inbox acceptance receipt")


def test_sidecar_checkpoints_and_delivers_real_domain_failure(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Deliver a complete domain event and retain the receiver receipt."""
    _assert_single_delivery(
        monkeypatch,
        tmp_path,
        source_state=domain_down_state(),
        expected_kind="domain_down",
    )


def test_sidecar_delivers_real_production_app_failure(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Use the same durable producer for a critical application-surface failure."""
    _assert_single_delivery(
        monkeypatch,
        tmp_path,
        source_state=production_failure_state(),
        expected_kind="production_failure",
    )


def test_sidecar_suppresses_duplicates_then_reescalates_and_recovers(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Hold one incident inside cooldown, re-escalate persistence, then resolve it."""
    configure_event_bus(monkeypatch)
    source_path = tmp_path / "source.json"
    state_path = tmp_path / "producer.json"
    write_state(source_path, domain_down_state())
    captured: list[JsonObject] = []
    transport_factory = partial(accepted_requests, captured)
    first = run_cycle(
        config_path=CONFIG_PATH,
        source_path=source_path,
        state_path=state_path,
        now=EVENT_TIME + 10.0,
        transport=transport_factory(),
    )
    quiet = run_cycle(
        config_path=CONFIG_PATH,
        source_path=source_path,
        state_path=state_path,
        now=EVENT_TIME + 100.0,
        transport=transport_factory(),
    )
    repeated = run_cycle(
        config_path=CONFIG_PATH,
        source_path=source_path,
        state_path=state_path,
        now=EVENT_TIME + 10.0 + REESCALATION_SECONDS,
        transport=transport_factory(),
    )
    recovered_state = domain_down_state()
    recovered_state["last_ok"] = {"unimixbrasil.com.br": True}
    prior_events = value_list(domain_down_state().get("events"))
    recovered_state["events"] = [
        *prior_events,
        {"ts": EVENT_TIME + 2_000.0, "kind": "domain_up", "domain": "unimixbrasil.com.br"},
    ]
    write_state(source_path, recovered_state)
    recovered = run_cycle(
        config_path=CONFIG_PATH,
        source_path=source_path,
        state_path=state_path,
        now=EVENT_TIME + 2_000.0,
        transport=transport_factory(),
    )
    kinds = [text_value(payload.get("event_kind")) for payload in captured]
    if first.delivered_count != 1 or quiet.staged_count != 0:
        pytest.fail("domain producer cooldown did not suppress a duplicate")
    if repeated.delivered_count != 1 or recovered.delivered_count != 1:
        pytest.fail("domain producer did not re-escalate or recover the incident")
    if kinds != ["domain_down", "domain_down", "domain_up"]:
        pytest.fail(f"domain event transition order is wrong: {kinds}")
    if load_domain_producer_state(state_path).incidents:
        pytest.fail("recovery did not close the producer incident receipt")


def test_sidecar_retains_failed_delivery_then_drains_after_backoff(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Persist a loud failed attempt and retry the same immutable delivery."""
    configure_event_bus(monkeypatch)
    source_path = tmp_path / "source.json"
    state_path = tmp_path / "producer.json"
    write_state(source_path, domain_down_state())
    attempts = 0

    def _fail_then_accept(request: Request) -> Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            unavailable_response = partial(Response, 503, request=request)
            return unavailable_response()
        return accepted_requests([]).handle_request(request)

    transport_factory = partial(MockTransport, _fail_then_accept)
    transport = transport_factory()
    failed = run_cycle(
        config_path=CONFIG_PATH,
        source_path=source_path,
        state_path=state_path,
        now=EVENT_TIME + 10.0,
        transport=transport,
    )
    too_soon = run_cycle(
        config_path=CONFIG_PATH,
        source_path=source_path,
        state_path=state_path,
        now=EVENT_TIME + 11.0,
        transport=transport,
    )
    drained = run_cycle(
        config_path=CONFIG_PATH,
        source_path=source_path,
        state_path=state_path,
        now=EVENT_TIME + 12.0,
        transport=transport,
    )
    retained = load_domain_producer_state(state_path)

    if failed.pending_count != 1 or failed.delivered_count != 0:
        pytest.fail(f"failed incident delivery was not retained: {failed}")
    if too_soon.pending_count != 1 or too_soon.delivered_count != 0:
        pytest.fail(f"delivery backoff was not respected: {too_soon}")
    if drained.pending_count != 0 or drained.delivered_count != 1:
        pytest.fail(f"retained incident delivery did not drain: {drained}")
    if retained.last_error is not None or retained.last_receiver_event_id is None:
        pytest.fail("successful retry did not clear the loud error and retain its receipt")
