# Copyright (c) 2026 PitchAI. All rights reserved.
"""Behavioral checks for durable monitoring-event state."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from domain_checks.event_bus import MONITORING_EVENT_KINDS, EventBusOutbox
from domain_checks.main import load_monitor_state
from domain_checks.testing import verify
from tests.event_bus_support import event_bus_config

if TYPE_CHECKING:
    from domain_checks.types import JsonObject


def _literal_event_kind(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call) or not node.args:
        return None
    function = node.func
    if not isinstance(function, ast.Attribute) or function.attr != "append":
        return None
    owner = function.value
    is_context_events = isinstance(owner, ast.Attribute) and owner.attr == "events"
    is_service_events = isinstance(owner, ast.Name) and owner.id == "events"
    first = node.args[0]
    if (is_context_events or is_service_events) and isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def test_duplicate_enqueue_and_tampered_persisted_identity_are_rejected() -> None:
    """Verify duplicate enqueue and tampered persisted identity are rejected."""
    outbox = EventBusOutbox(event_bus_config())
    first = outbox.enqueue("domain_up", occurred_at=1.0, details={"domain": "example.test"})
    second = outbox.enqueue("domain_up", occurred_at=1.0, details={"domain": "example.test"})
    verify(first == second)
    verify(outbox.pending_count == 1)

    state = outbox.to_state()
    state[0]["payload"]["details"]["domain"] = "tampered.test"
    with pytest.raises(RuntimeError, match="delivery identity"):
        _ = EventBusOutbox(event_bus_config(), entries=state)


def test_monitor_state_codec_preserves_outbox_across_restart(tmp_path: Path) -> None:
    """Verify the state codec round-trips a pending event across restart."""
    outbox = EventBusOutbox(event_bus_config())
    delivery_id = outbox.enqueue(
        "domain_down",
        occurred_at=1_784_001_600.0,
        details={"domain": "internal.pitchai.net"},
    )
    state_path = tmp_path / "state.json"
    _ = state_path.write_text(
        json.dumps({"version": 6, "event_bus_outbox": outbox.to_state()}),
        encoding="utf-8",
    )

    loaded = load_monitor_state(state_path)
    entries = loaded["event_bus_outbox"]
    if not isinstance(entries, list):
        pytest.fail("persisted Events Bus outbox was not a list")
    persisted_entries: list[JsonObject] = []
    for entry in entries:
        if not isinstance(entry, dict):
            pytest.fail("persisted Events Bus entry was not a mapping")
        persisted_entries.append(entry)
    restored = EventBusOutbox(event_bus_config(), entries=persisted_entries)

    verify(restored.pending_count == 1)
    verify(restored.to_state()[0]["payload"]["delivery_id"] == delivery_id)


def test_monitor_state_codec_preserves_malformed_outbox_for_loud_rejection(tmp_path: Path) -> None:
    """Verify malformed persisted state reaches the validating boundary unchanged."""
    state_path = tmp_path / "state.json"
    _ = state_path.write_text(
        json.dumps({"version": 6, "event_bus_outbox": {"unexpected": "object"}}),
        encoding="utf-8",
    )

    loaded = load_monitor_state(state_path)

    verify(loaded["event_bus_outbox"] == {"unexpected": "object"})


def test_monitor_transition_catalog_is_fully_supported() -> None:
    """Verify composed monitor cycles emit only supported transition kinds."""
    domain_checks = Path(__file__).parents[1] / "domain_checks"
    source_paths = list(domain_checks.glob("monitor_cycle_*.py"))
    source_paths.extend((domain_checks / "monitor_browser.py", domain_checks / "monitor_service.py"))
    emitted: set[str] = set()
    for source_path in source_paths:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        nodes = ast.walk(tree)
        kinds = {_literal_event_kind(node) for node in nodes}
        emitted.update(kind for kind in kinds if kind is not None)
    required = {
        "service_started",
        "api_contract_degraded",
        "api_contract_recovered",
        "synthetic_degraded",
        "synthetic_recovered",
        "web_vitals_degraded",
        "web_vitals_recovered",
    }

    verify(emitted <= MONITORING_EVENT_KINDS)
    verify(required <= emitted)
