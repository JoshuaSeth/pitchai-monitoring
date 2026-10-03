# Copyright (c) 2026 PitchAI. All rights reserved.
"""Pure transition and exception contracts of recorded-history phases."""

from __future__ import annotations

import asyncio
import unittest
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

from httpx import AsyncClient

from .alert_settings import AlertSettings
from .cycle_channels import CycleChannels
from .dft_test_support import require, require_error
from .dispatch_records import DispatchRecords
from .health_state import HealthState
from .history_phase_context import HistoryComputeBoundary, HistoryFrame
from .history_phase_health import HistoryHealth
from .metrics_red import RedViolation
from .signal_history import SignalHistory
from .telegram import TelegramConfig

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject, JsonValue


class TestHistoryPhase(unittest.IsolatedAsyncioTestCase):
    """Exercise routing filters and event shape without invoking any transport."""

    @staticmethod
    def test_filter_preserves_duplicates_and_independent_recovery() -> None:
        """Only alertable violations affect the sampled debounce counters."""
        events: list[tuple[str, float | None, dict[str, JsonValue]]] = []

        def capture(kind: str, ts: float, fields: JsonObject) -> None:
            events.append((kind, ts, fields))

        client = cast("AsyncClient", MagicMock(spec=AsyncClient))
        channels = CycleChannels(client, TelegramConfig("synthetic-unsent", "synthetic"), None, {},
                                 DispatchRecords(), {})
        frame = HistoryFrame({}, {"alert.invalid"}, 100.0, channels, capture, SignalHistory({}))
        settings = AlertSettings(enabled=True, down_after_failures=1, up_after_successes=2,
                                 dispatch_on_degraded=False, notify_on_recovery=False)
        state = HealthState()
        health = HistoryHealth("red", state, settings, frame, "synthetic excluded=%s")
        wanted = RedViolation("alert.invalid", ["failure"], 3, 100.0, None, None)
        hidden = RedViolation("dashboard.invalid", ["failure"], 3, 100.0, None, None)
        observation = health.observe([wanted, hidden, wanted])
        require(condition=observation.violations == [wanted, wanted] and observation.alerted_down,
                message="filter reordered/deduplicated actual violations")
        frame.degraded("red_degraded", [value.domain for value in observation.violations])
        _ = health.observe([hidden])
        require(condition=not state.last_ok, message="one clean routed sample bypassed recovery streak")
        empty: list[RedViolation] = []
        _ = health.observe(empty)
        require(condition=state.last_ok, message="consecutive clean samples failed recovery")
        require(condition=frame.signals.samples == {"red": [[100.0, 0, 2], [100.0, 0, 0], [100.0, 1, 0]]},
                message="sample count or transition ordering changed")
        require(condition=events == [("red_degraded", 100.0, {
            "violations": 2, "domains": ["alert.invalid", "alert.invalid"],
        })], message="degraded event payload changed")

    @staticmethod
    def test_event_bounds_keep_full_count_and_original_timestamp() -> None:
        """Event domain samples are bounded independently of violation count."""
        events: list[dict[str, JsonValue]] = []

        def capture(kind: str, ts: float, fields: JsonObject) -> None:
            events.append({"kind": kind, "ts": ts, **fields})

        client = cast("AsyncClient", MagicMock(spec=AsyncClient))
        channels = CycleChannels(client, TelegramConfig("synthetic-unsent", "synthetic"), None, {},
                                 DispatchRecords(), {})
        frame = HistoryFrame({}, set(), 123.5, channels, capture, SignalHistory({}))
        indices = range(25)
        domains = [f"domain-{index}.invalid" for index in indices]
        frame.degraded("slo_degraded", domains)
        frame.recovered("slo_recovered")
        require(condition=events == [
            {"kind": "slo_degraded", "ts": 123.5, "violations": 25, "domains": list(domains[:20])},
            {"kind": "slo_recovered", "ts": 123.5},
        ], message="event bounds or original time changed")
        require(condition=not channels.dispatch_available("slo", "synthetic active"),
                message="missing dispatch config became enabled")
        with require_error(RuntimeError, "without configuration"):
            _ = channels.dispatch_inputs()

    async def test_compute_error_keeps_logged_fallback_and_cancellation_propagates(self) -> None:
        """Only ordinary compute failures take the existing empty fallback."""
        with self.assertLogs("service-monitoring", level="ERROR"), HistoryComputeBoundary("synthetic compute"):
            _ = int("synthetic invalid number")

        async def cancelled() -> None:
            """Exercise cancellation at the observation boundary.

            Raises:
                CancelledError: The synthetic observation is cancelled.
            """
            with HistoryComputeBoundary("synthetic compute"):
                await asyncio.sleep(0)
                raise asyncio.CancelledError

        results = await asyncio.gather(cancelled(), return_exceptions=True)
        require(condition=isinstance(results[0], asyncio.CancelledError), message="compute swallowed cancellation")

    def test_successful_boundary_does_not_change_result(self) -> None:
        """The exception boundary cannot fabricate a result or emit a message."""
        result = ["original"]
        with self.assertNoLogs("service-monitoring"), HistoryComputeBoundary("synthetic compute"):
            result.append("observed")
        require(condition=result == ["original", "observed"], message="compute boundary altered results")
