# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated cooldown and retained collection contracts."""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING
from unittest.mock import patch

from .dft_test_support import require
from .dispatch_client import DispatchConfig
from .dispatch_records import DispatchRecords
from .dispatch_state import dispatch_disable, dispatch_is_enabled, dispatch_should_notify

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject


class DispatchStateTests(unittest.TestCase):
    """Preserve state identities and existing limit/clock boundaries."""

    @staticmethod
    def test_missing_configuration_does_not_reenable_state() -> None:
        """Configuration remains necessary even after an elapsed cooldown."""
        state: JsonObject = {"enabled": False, "disabled_until_monotonic": 1, "disabled_reason": "limited"}
        with patch("domain_checks.dispatch_state.time.monotonic", return_value=100):
            require(condition=not dispatch_is_enabled(None, state), message="missing config enabled dispatch")
        require(condition=state["enabled"] is False, message="missing config mutated stop state")

    @staticmethod
    def test_permanent_disable_and_exact_cooldown_boundary() -> None:
        """Only the configured finite deadline can automatically re-enable."""
        state: JsonObject = {}
        config = DispatchConfig("https://dispatch.invalid", "synthetic")
        with patch("domain_checks.dispatch_state.time.monotonic", return_value=100):
            dispatch_disable(state, reason="auth")
            require(condition=not dispatch_is_enabled(config, state), message="permanent stop cleared")
            dispatch_disable(state, reason="limited", cooldown_seconds=-1)
            require(condition=not dispatch_is_enabled(config, state), message="minimum cooldown ignored")
        with patch("domain_checks.dispatch_state.time.monotonic", return_value=101):
            require(condition=dispatch_is_enabled(config, state), message="deadline equality did not re-enable")
        require(
            condition=state["disabled_reason"] is None and state["disabled_until_monotonic"] is None,
            message="expired reason/deadline survived",
        )

    @staticmethod
    def test_notice_cadence_and_backwards_clock() -> None:
        """Notice observation updates only when the complete interval elapsed."""
        state: JsonObject = {"last_notify_monotonic": 100}
        with patch("domain_checks.dispatch_state.time.monotonic", return_value=90):
            require(condition=not dispatch_should_notify(state, min_interval_seconds=10), message="backwards notice")
        with patch("domain_checks.dispatch_state.time.monotonic", return_value=110):
            require(condition=dispatch_should_notify(state, min_interval_seconds=10), message="boundary notice missing")
            require(condition=not dispatch_should_notify(state, min_interval_seconds=10), message="duplicate notice")

    @staticmethod
    def test_history_and_events_trim_without_copying_entries() -> None:
        """Overflow prunes old prefixes and keeps the original last-record object."""
        history: list[JsonObject] = [{}] * 2000
        events: list[JsonObject] = [{}] * 10_000
        last: dict[str, JsonObject] = {}
        record: JsonObject = {"ts": 2.0, "queue_state": "processed", "ok": True}
        DispatchRecords(history, last, events).record(record, "synthetic", "Fixture")
        history_size, events_size = 1500, 8000
        require(condition=len(history) == history_size and len(events) == events_size, message="prefix limits changed")
        require(condition=history[-1] is record and last["synthetic"] is record, message="record references copied")
        require(
            condition=events[-1]["kind"] == "dispatch_completed" and events[-1]["ts"] == record["ts"],
            message="completion event changed",
        )

    @staticmethod
    def test_malformed_event_time_keeps_history_without_fabricating_event() -> None:
        """An invalid retained timestamp cannot become a new completion time."""
        history: list[JsonObject] = []
        events: list[JsonObject] = []
        record: JsonObject = {"ts": "invalid"}
        DispatchRecords(history=history, events=events).record(record, "synthetic", "Fixture")
        require(condition=history == [record] and not events, message="invalid timestamp lost record or invented event")
