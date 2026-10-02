# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated file-boundary and schema migration guarantees for monitor state."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from .dft_test_support import require, require_error
from .monitor_state import decode_monitor_state, load_last_ok_state, load_monitor_state
from .state_sections import default_monitor_state
from .state_storage import read_state_value, write_state_atomic

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject


class TestMonitorState(unittest.TestCase):
    """Exercise only synthetic temporary files and pure decoded payloads."""

    @staticmethod
    def test_legacy_forms_keep_original_early_return() -> None:
        """Version and health survive; modern fields are ignored on legacy input."""
        legacy = decode_monitor_state({"last_ok": {"first": False}, "events": [{"kind": "ignored"}], "version": "4"})
        expected = default_monitor_state()
        expected["last_ok"] = {"first": False}
        expected["version"] = 4
        require(condition=legacy == expected, message="legacy last-ok migration changed")
        boolean_map = decode_monitor_state({"first": False, "second": True})
        expected["last_ok"] = {"first": False, "second": True}
        expected["version"] = 6
        require(condition=boolean_map == expected, message="legacy raw boolean mapping changed")

    @staticmethod
    def test_modern_state_preserves_receipts_and_original_version() -> None:
        """Restart decoding cannot fabricate migration, delivery or recovery."""
        event: JsonObject = {"kind": "synthetic-failure", "delivery_id": "fixture-retained"}
        raw: JsonObject = {"version": "3", "history_ok_mode": " OBSERVED ", "last_ok": {"first": False},
                           "fail_streak": {"first": "2"}, "success_streak": {"first": 1},
                           "events": [event, event], "event_bus_outbox": [event], "dispatch_last": event,
                           "host_last_snapshot": {"synthetic": True}, "browser_degraded_active": True,
                           "browser_degraded_first_seen_ts": "9", "browser_launch_last_error": " kept "}
        decoded = decode_monitor_state(raw)
        version = 3
        require(condition=decoded["version"] == version and decoded["history_ok_mode"] == "observed",
                message="state version or history policy changed")
        require(condition=decoded["last_ok"] == {"first": False} and decoded["fail_streak"] == {"first": 2},
                message="unresolved domain health reset")
        require(condition=decoded["events"] == [event, event] and decoded["event_bus_outbox"] == [event],
                message="retained event or pending delivery changed")
        require(condition=decoded["dispatch_last"] is event and decoded["browser_launch_last_error"] == " kept ",
                message="retained diagnostic behavior changed")

    def test_missing_file_is_silent_and_creates_nothing(self) -> None:
        """An initial state read must not create a directory, file or incident."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "absent" / "state.json"
            with self.assertNoLogs("service-monitoring"):
                state = load_monitor_state(path)
            require(condition=state == default_monitor_state(), message="missing state defaults changed")
            require(condition=not path.parent.exists(), message="read-only state load created a path")

    def test_bad_file_warns_and_falls_back_without_rewriting(self) -> None:
        """Malformed JSON and invalid encoding retain warnings and original bytes."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            for content in (b"{invalid-json", b"\xff"):
                _ = path.write_bytes(content)
                with self.assertLogs("service-monitoring", level="WARNING") as captured:
                    state = load_monitor_state(path)
                require(condition=state == default_monitor_state() and path.read_bytes() == content,
                        message="failed state read modified bytes or defaults")
                require(condition=len(captured.records) == 1, message="read warning count changed")
            with self.assertLogs("service-monitoring", level="WARNING"):
                require(condition=read_state_value(Path(directory)) is None, message="directory state read succeeded")

    @staticmethod
    def test_atomic_write_and_last_ok_view_preserve_existing_schema() -> None:
        """The same sorted Unicode JSON is installed through a sibling temporary."""
        payload: JsonObject = {"last_ok": {"first": False}, "fail_streak": {"first": 2}, "label": "synthetic-ação"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "state.json"
            write_state_atomic(path, payload)
            expected = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            require(condition=path.read_text(encoding="utf-8") == expected,
                    message="persisted JSON encoding changed")
            require(condition=not path.with_name("state.json.tmp").exists(), message="successful write left temporary")
            before = path.read_bytes()
            require(condition=load_last_ok_state(path) == {"first": False}, message="legacy last-ok view changed")
            require(condition=path.read_bytes() == before, message="last-ok load rewrote state")

    @staticmethod
    def test_replace_failure_propagates_and_preserves_current_state() -> None:
        """An unsuccessful write cannot replace the retained failure state."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            write_state_atomic(path, {"last_ok": {"first": False}})
            before = path.read_bytes()
            with (
                patch.object(Path, "replace", side_effect=PermissionError("synthetic replacement refusal")),
                require_error(PermissionError, "synthetic replacement refusal"),
            ):
                write_state_atomic(path, {"last_ok": {"first": True}})
            require(condition=path.read_bytes() == before, message="failed replacement changed current state")
            require(condition=path.with_name("state.json.tmp").is_file(),
                    message="legacy failed-write evidence vanished")
