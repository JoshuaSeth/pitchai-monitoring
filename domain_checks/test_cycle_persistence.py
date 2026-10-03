# Copyright (c) 2026 PitchAI. All rights reserved.
"""Synthetic state files and local outbox objects exercise persistence boundaries."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from .browser_state import restore_browser_state
from .cycle_health_state import CycleHealthState
from .cycle_persistence import CyclePersistence, restore_outbox
from .cycle_records import CycleRecords
from .dft_cycle import DftCycle
from .dft_test_support import require, require_error
from .event_bus import DeliveryAttempt, EventBusConfig, EventBusOutbox

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject


def fixture(path: Path | None = None, outbox: EventBusOutbox | None = None) -> CyclePersistence:
    """Return state with no live source, configured journal or delivery function."""
    records = CycleRecords()
    health = CycleHealthState()
    health.restore({})
    return CyclePersistence(path, records, health, restore_browser_state({}, 0), DftCycle(None), outbox)


def config_fixture() -> EventBusConfig:
    """Return inert signing configuration; tests never call a network transport."""
    return EventBusConfig("https://receiver.invalid/events", "synthetic-private-test-secret-00000",
                          "test", "synthetic", None)


class PersistenceTests(unittest.IsolatedAsyncioTestCase):
    """Exercise cancellation, record ownership and file failure without outgoing calls."""

    @staticmethod
    def test_snapshot_aliases_and_write_counter_timing() -> None:
        """The written count precedes reset; inner domain records remain shared."""
        with tempfile.TemporaryDirectory(prefix="monitor-state-test-") as directory:
            path = Path(directory) / "state.json"
            state = fixture(path)
            previous_count = 3
            state.health.write_fail_streak = previous_count
            snapshot = state.snapshot()
            require(condition=snapshot["last_ok"] is state.records.domains.last_ok, message="alias copied")
            state.persist("cycle")
            saved = cast("JsonObject", json.loads(path.read_text(encoding="utf-8")))
            meta = cast("JsonObject", saved["meta"])
            require(condition=meta["state_write_fail_streak"] == previous_count, message="saved count reset early")
            require(condition=int(state.health.write_fail_streak) == 0, message="successful write failed to reset")

    @staticmethod
    def test_immediate_outbox_write_and_restore() -> None:
        """A real local queue is persisted on enqueue, with no transport or new journal."""
        with tempfile.TemporaryDirectory(prefix="monitor-outbox-test-") as directory:
            path = Path(directory) / "state.json"
            outbox = EventBusOutbox(config_fixture())
            state = fixture(path, outbox)
            observed = 100
            state.event("domain_down", observed, {"domain": "fixture.invalid"})
            saved = cast("JsonObject", json.loads(path.read_text(encoding="utf-8")))
            resumed = restore_outbox(config_fixture(), saved)
            require(condition=resumed is not None and resumed.pending_count == 1, message="pending event lost")
            require(condition=state.records.activity.events[0]["ts"] == observed, message="original event age lost")

    @staticmethod
    def test_enqueue_failure_does_not_append_or_write() -> None:
        """Refusal by the existing queue precedes local history mutation."""
        enqueue = MagicMock(side_effect=RuntimeError("synthetic full queue"))
        outbox = MagicMock(spec=EventBusOutbox, enqueue=enqueue)
        state = fixture(Path("/unused-synthetic-state"), cast("EventBusOutbox", outbox))
        with (patch("domain_checks.cycle_persistence.write_state_atomic") as writer,
              require_error(RuntimeError, "synthetic full queue")):
            state.event("domain_down", 100, {})
        writer.assert_not_called()
        require(condition=not state.records.activity.events, message="failed enqueue appended event")

    @staticmethod
    def test_write_failure_retains_pending_event_and_increments() -> None:
        """Ordinary persistence failure stays counted, with its queued record retained."""
        outbox = EventBusOutbox(config_fixture())
        state = fixture(Path("/unused-synthetic-state"), outbox)
        previous_count = 2
        state.health.write_fail_streak = previous_count
        with patch("domain_checks.cycle_persistence.write_state_atomic", side_effect=OSError("synthetic refusal")):
            state.event("domain_down", 100, {})
        require(condition=int(state.health.write_fail_streak) == previous_count + 1, message="write failure erased")
        require(condition=outbox.pending_count == len(state.records.activity.events) == 1,
                message="failure lost pending event")

    @staticmethod
    async def test_cancelled_write_is_not_a_recovery_or_counted_ordinary_failure() -> None:
        """System cancellation propagates across the file boundary without changing counters."""
        state = fixture(Path("/unused-synthetic-state"))
        previous_count = 2
        state.health.write_fail_streak = previous_count
        with patch("domain_checks.cycle_persistence.write_state_atomic", side_effect=asyncio.CancelledError):
            outcome = await asyncio.gather(asyncio.to_thread(state.persist, "browser_notice"), return_exceptions=True)
        require(condition=isinstance(outcome[0], asyncio.CancelledError), message="cancellation suppressed")
        require(condition=state.health.write_fail_streak == previous_count,
                message="cancellation changed ordinary count")

    @staticmethod
    def test_disabled_persistence_preserves_event_cap_and_counter() -> None:
        """In-memory event retention has the same threshold and shallow references."""
        state = fixture()
        previous_count = 2
        state.health.write_fail_streak = previous_count
        state.records.activity.events.extend({"ts": index} for index in range(10_000))
        state.event("domain_down", 100, {})
        expected_count, first_retained = 8000, 2001
        require(condition=len(state.records.activity.events) == expected_count, message="event cap changed")
        require(condition=state.records.activity.events[0]["ts"] == first_retained, message="wrong trim boundary")
        state.persist("cycle")
        require(condition=state.health.write_fail_streak == previous_count, message="no-path write invented success")

    @staticmethod
    def test_invalid_queue_type_retains_runtime_error_contract() -> None:
        """Type errors remain loud and compatible with existing RuntimeError handlers."""
        with require_error(RuntimeError, "outbox must be a list"):
            restore_outbox(config_fixture(), {"event_bus_outbox": "invalid"})
        require(condition=restore_outbox(None, {"event_bus_outbox": "unused"}) is None,
                message="disabled queue validated unused state")

    @staticmethod
    async def test_flush_uses_existing_client_and_attempt_results() -> None:
        """Only the fake outbox is awaited; unsent attempts cannot become receipts."""
        flush = AsyncMock(return_value=[DeliveryAttempt("synthetic", success=False, status_code=None,
                                                       event_id=None, error="not sent")])
        outbox = MagicMock(spec=EventBusOutbox, pending_count=1, flush=flush)
        state = fixture(outbox=cast("EventBusOutbox", outbox))
        client = cast("AsyncClient", MagicMock(spec=AsyncClient))
        await state.flush(client)
        flush.assert_awaited_once_with(client)
        require(condition=cast("EventBusOutbox", outbox).pending_count == 1,
                message="pending state changed outside queue")
