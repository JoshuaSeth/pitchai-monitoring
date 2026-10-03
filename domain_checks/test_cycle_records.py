# Copyright (c) 2026 PitchAI. All rights reserved.
"""Restart, alias and migration boundaries for the native cycle records."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from .cycle_records import CycleRecords
from .dft_test_support import require
from .state_storage import write_state_atomic

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject


def retained() -> JsonObject:
    """Return private synthetic restart state with actual normalized collections."""
    return {"history_ok_mode": "effective", "last_ok": {"fixture.invalid": False},
            "fail_streak": {"fixture.invalid": 3}, "success_streak": {"fixture.invalid": 1},
            "history": {"fixture.invalid": [[10, False, 1, 2, 503]]},
            "signal_history": {"fixture": [[10, 1]]}, "host_last_snapshot": {"clock": 10},
            "dispatch_history": [{"state_key": "fixture"}], "dispatch_last": {"fixture": {"ok": False}},
            "events": [{"kind": "fixture", "ts": 10}]}


class CycleRecordsTests(unittest.IsolatedAsyncioTestCase):
    """Use isolated files, with no channel, browser or process observations."""

    @staticmethod
    def test_no_path_keeps_independent_empty_collections() -> None:
        """A disabled writer does not read or share another cycle's records."""
        with patch("domain_checks.cycle_records.load_monitor_state") as load:
            first = CycleRecords.load(None, down_after_failures=2, up_after_successes=2)
            second = CycleRecords.load(None, down_after_failures=2, up_after_successes=2)
        load.assert_not_called()
        first.activity.events.append({"kind": "fixture"})
        require(condition=not second.activity.events and not first.disk, message="disabled persistence shared state")

    @staticmethod
    def test_real_restart_preserves_disk_and_mutable_aliases() -> None:
        """Resume normalized counters without rewriting or refreshing stored evidence."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            write_state_atomic(path, retained())
            before = path.read_bytes(), path.stat().st_mtime_ns
            state = CycleRecords.load(path, down_after_failures=2, up_after_successes=2)
            require(condition=(path.read_bytes(), path.stat().st_mtime_ns) == before, message="restart wrote state")
            require(condition=state.domains.last_ok == {"fixture.invalid": False}, message="failure lost at restart")
            require(condition=state.activity.events is state.disk["events"], message="event alias changed")
            state.activity.events.append({"kind": "new"})
            state.domains.last_ok["fixture.invalid"] = True
            snapshot = state.snapshot()
            require(condition=snapshot["last_ok"] is state.domains.last_ok, message="health snapshot copied live map")
            event_slice = snapshot["events"]
            require(condition=event_slice == state.activity.events and event_slice is not state.activity.events,
                    message="event slice semantics changed")
            require(condition=snapshot["history"] is state.history, message="history snapshot copied live map")

    @staticmethod
    def test_snapshot_caps_only_exported_lists() -> None:
        """Capture the most recent records without deleting the live retained lists."""
        state = CycleRecords()
        event_numbers = range(2100)
        state.activity.events = [{"number": value} for value in event_numbers]
        dispatch_numbers = range(600)
        state.activity.dispatch_history = [{"number": value} for value in dispatch_numbers]
        snapshot = state.snapshot()
        expected = {"events": state.activity.events[-2000:], "dispatch_history": state.activity.dispatch_history[-500:]}
        matches = all(snapshot[key] == value for key, value in expected.items())
        require(condition=matches, message="caps changed")
        lengths = len(state.activity.events), len(state.activity.dispatch_history)
        require(condition=lengths == (2100, 600), message="live data deleted")

    @staticmethod
    def test_observed_history_migrates_with_original_debounce() -> None:
        """A single transient failure remains healthy in migrated SLO samples."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            data = retained()
            data["history_ok_mode"] = "observed"
            data["history"] = {"fixture.invalid": [[10, True], [20, False], [30, False], [40, True], [50, True]]}
            write_state_atomic(path, data)
            state = CycleRecords.load(path, down_after_failures=2, up_after_successes=2)
            flags = [row[1] for row in state.history["fixture.invalid"]]
            require(condition=flags == [True, True, False, False, True], message="history debounce changed")

    @staticmethod
    async def test_migration_failure_keeps_history_and_cancellation_propagates() -> None:
        """Ordinary migration faults retain data while shutdown remains observable."""
        state = CycleRecords(history={"fixture.invalid": [[10, False]]})
        original = state.history
        with patch("domain_checks.cycle_records.migrate_effective_history", side_effect=ValueError("fixture")):
            state.migrate(2, 2)
        require(condition=state.history is original, message="failed migration replaced records")
        with patch("domain_checks.cycle_records.migrate_effective_history", side_effect=asyncio.CancelledError):
            outcome = await asyncio.gather(asyncio.to_thread(state.migrate, 2, 2), return_exceptions=True)
        require(condition=isinstance(outcome[0], asyncio.CancelledError), message="migration swallowed cancellation")

    @staticmethod
    def test_unreadable_and_legacy_restart_follow_existing_loader() -> None:
        """Fallback and old all-boolean state still use the canonical decoder."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            absent = CycleRecords.load(path, down_after_failures=1, up_after_successes=1)
            require(condition=not absent.domains.last_ok, message="missing state invented history")
            _ = path.write_text(json.dumps({"fixture.invalid": False}), encoding="utf-8")
            legacy = CycleRecords.load(path, down_after_failures=1, up_after_successes=1)
            require(condition=legacy.domains.last_ok == {"fixture.invalid": False}, message="legacy failure reset")
