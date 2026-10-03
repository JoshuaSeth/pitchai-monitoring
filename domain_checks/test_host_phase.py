# Copyright (c) 2026 PitchAI. All rights reserved.
"""Host-phase state and exception ordering with synthetic observations only."""

from __future__ import annotations

import asyncio
import unittest
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from .cycle_channels import CycleChannels
from .dft_test_support import require, require_error
from .dispatch_records import DispatchRecords
from .health_state import HealthState
from .host_observations import HostObservations
from .host_phase import HostPhase
from .resource_settings import load_host_settings
from .signal_history import SignalHistory
from .telegram import TelegramConfig

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject


def _fixture(*, enabled: bool = True) -> tuple[HostPhase, list[JsonObject]]:
    settings = load_host_settings({"host_health": {
        "enabled": enabled, "down_after_failures": 1, "up_after_successes": 2,
        "mem_used_percent_max": 80, "notify_on_recovery": False, "dispatch_on_degraded": False,
    }})
    events: list[JsonObject] = []

    def record(kind: str, timestamp: float, fields: JsonObject) -> None:
        events.append({"kind": kind, "ts": timestamp, **fields})

    client = cast("AsyncClient", MagicMock(spec=AsyncClient))
    channels = CycleChannels(client, TelegramConfig("synthetic-unsent", "synthetic"), None, {},
                             DispatchRecords(), {})
    return HostPhase(settings, HealthState(), HostObservations(), channels, record, SignalHistory({})), events


class TestHostObservations(unittest.TestCase):
    """Retain partial numeric conversion and shallow-copy behavior explicitly."""

    @staticmethod
    def test_invalid_idle_keeps_updated_total_and_old_idle() -> None:
        """A bad second conversion does not undo the original first assignment."""
        state = HostObservations(1, 2)
        state.advance_cpu({"cpu_prev_total_next": "3", "cpu_prev_idle_next": "bad"})
        require(condition=(state.cpu_prev_total, state.cpu_prev_idle) == (3, 2), message="CPU order changed")

    @staticmethod
    def test_missing_counter_preserves_both_baselines() -> None:
        """Both next counters must exist before either assignment is attempted."""
        state = HostObservations(1, 2)
        state.advance_cpu({"cpu_prev_total_next": 3})
        require(condition=(state.cpu_prev_total, state.cpu_prev_idle) == (1, 2), message="missing CPU changed state")

    @staticmethod
    def test_dashboard_copy_keeps_nested_identity_and_input() -> None:
        """Only the copy loses CPU-next fields; nested diagnostics stay shared."""
        snapshot: JsonObject = {"disk": {"/fixture": {"used_percent": 70}},
                                "cpu_prev_total_next": 3, "cpu_prev_idle_next": 2}
        state = HostObservations()
        state.capture(snapshot)
        require(condition=state.last_snapshot is not snapshot, message="dashboard aliases input map")
        require(condition=state.last_snapshot["disk"] is snapshot["disk"], message="nested diagnostic copied")
        require(condition="cpu_prev_total_next" in snapshot and "cpu_prev_total_next" not in state.last_snapshot,
                message="CPU-next visibility changed")


class TestHostPhase(unittest.IsolatedAsyncioTestCase):
    """Exercise actual phase sequencing while replacing host and transport input."""

    @staticmethod
    async def test_warning_failure_retains_observed_state_and_event() -> None:
        """Transport failure occurs after CPU, dashboard, health and event mutation."""
        phase, events = _fixture()
        expected_total = 300
        snapshot: JsonObject = {"mem_used_percent": 90, "cpu_prev_total_next": expected_total, "cpu_prev_idle_next": 40}
        with (patch("domain_checks.host_phase.collect_host_snapshot", return_value=snapshot),
              patch("domain_checks.cycle_channels.send_telegram_message_chunked",
                    new=AsyncMock(side_effect=OSError("synthetic"))),
              require_error(OSError, "synthetic")):
            _ = await phase.run(100)
        require(condition=not phase.health.last_ok and phase.observations.cpu_prev_total == expected_total,
                message="warning exception rolled back observed state")
        require(condition=phase.observations.last_snapshot == {"mem_used_percent": 90}, message="snapshot missing")
        require(condition=events == [{"kind": "host_health_degraded", "ts": 100.0,
                                      "violations": ["Memory: 90.0% >= 80.0%"]}], message="event ordering changed")

    @staticmethod
    async def test_cancellation_retains_same_state_boundary() -> None:
        """Cancellation propagates after observation without becoming recovery."""
        phase, events = _fixture()
        with (patch("domain_checks.host_phase.collect_host_snapshot", return_value={"mem_used_percent": 90}),
              patch("domain_checks.cycle_channels.send_telegram_message_chunked",
                    new=AsyncMock(side_effect=asyncio.CancelledError))):
            results = await asyncio.gather(phase.run(100), return_exceptions=True)
        require(condition=isinstance(results[0], asyncio.CancelledError), message="cancellation swallowed")
        require(condition=not phase.health.last_ok and len(events) == 1, message="cancellation changed transition")

    @staticmethod
    async def test_disabled_phase_does_not_read_or_reset() -> None:
        """Disabled monitoring retains restart state and returns absent observations."""
        phase, events = _fixture(enabled=False)
        baseline = 12
        phase.observations.cpu_prev_total = baseline
        with patch("domain_checks.host_phase.collect_host_snapshot", side_effect=AssertionError("host read")):
            result = await phase.run(100)
        require(condition=result == (None, None) and not events, message="disabled phase observed or emitted")
        require(condition=phase.observations.cpu_prev_total == baseline, message="disabled phase reset baseline")
