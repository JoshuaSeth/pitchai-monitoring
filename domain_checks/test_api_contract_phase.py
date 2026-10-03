# Copyright (c) 2026 PitchAI. All rights reserved.
"""Synthetic API scheduling, transition and transport-boundary compatibility."""

from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from .api_contract_phase import ApiContractPhase
from .api_contract_settings import ApiContractSettings
from .browser_phase_context import BrowserProbeState
from .common_check import DomainCheckSpec
from .cycle_channels import CycleChannels
from .dft_test_support import require
from .dispatch_records import DispatchRecords
from .domain_entries import normalize_domain_entries
from .metrics_api_contract import ApiContractCheckResult
from .probe_frame import ProbeDomains, ProbeFrame
from .signal_history import SignalHistory
from .telegram import TelegramConfig

if TYPE_CHECKING:
    from .api_contract_phase import ApiContractCall
    from .config_values import ConfigValue
    from .event_bus_delivery import JsonObject


def fixture(probe: AsyncMock) -> tuple[ApiContractPhase, ProbeFrame, list[JsonObject]]:
    """Return existing route references backed by mocks and reserved domain names."""
    events: list[JsonObject] = []

    def event(kind: str, stamp: float, fields: JsonObject) -> None:
        events.append({"kind": kind, "ts": stamp, **fields})

    raw: list[ConfigValue] = [
        {"domain": "active.invalid", "alert_policy": {"telegram": "critical"}},
        {"domain": "muted.invalid", "alert_policy": {"telegram": "dashboard-only", "reason": "fixture"}},
    ]
    entries = normalize_domain_entries(raw)
    specs = [DomainCheckSpec(entry.domain, "https://fixture.invalid", api_contract_checks=[{"path": "/health"}])
             for entry in entries]
    channels = CycleChannels(cast("AsyncClient", MagicMock(spec=AsyncClient)),
        TelegramConfig("synthetic-unsent", "fixture"), None, {}, DispatchRecords(events=events), {})
    known = {entry.domain for entry in entries}
    frame = ProbeFrame(200, ProbeDomains(specs, known, {"active.invalid"}),
                       channels, event, SignalHistory({}))
    settings = ApiContractSettings.read({"api_contract": {"enabled": True, "interval_minutes": 1,
        "down_after_failures": 1, "up_after_successes": 2, "notify_on_recovery": True}})
    return ApiContractPhase(settings, BrowserProbeState({}, {}, {}, {}),
                            {entry.domain: entry for entry in entries}, probe), frame, events


def result(domain: str, *, healthy: bool) -> ApiContractCheckResult:
    """Return a synthetic observation without endpoint access."""
    return ApiContractCheckResult(domain, "fixture", healthy, "https://fixture.invalid/health", 200 if healthy else 503,
                                   12.0, None if healthy else "synthetic failure", {})


class ApiContractPhaseTests(unittest.IsolatedAsyncioTestCase):
    """Native async tasks with local captures and zero real transport calls."""

    @staticmethod
    async def test_disabled_and_not_due_leave_attempts_unchanged() -> None:
        """Disabled and premature cycles cannot invent fresh observations."""
        probe = AsyncMock()
        phase, frame, events = fixture(probe)
        disabled = replace(phase, settings=ApiContractSettings.read({}))
        with patch("domain_checks.api_contract_phase.time.time", side_effect=AssertionError("clock read")):
            await disabled.run(frame)
        phase.state.last_run_ts.update({"active.invalid": 150, "muted.invalid": 150})
        with patch("domain_checks.api_contract_phase.time.time", return_value=200):
            await phase.run(frame)
        probe.assert_not_awaited()
        require(condition=(events, phase.state.last_run_ts["active.invalid"]) == ([], 150),
                message="skip changed state")

    @staticmethod
    async def test_down_then_two_success_recovery_preserves_route_and_order() -> None:
        """Both domains retain health; only the existing active route may recover."""
        healthy = False
        calls: list[str] = []

        def observe(inputs: ApiContractCall) -> list[ApiContractCheckResult]:
            calls.append(inputs["domain"])
            return [result(inputs["domain"], healthy=healthy)]

        phase, frame, events = fixture(AsyncMock(side_effect=observe))
        notice = AsyncMock(return_value=None)
        recovery = AsyncMock(return_value=(False, {}))
        first_stamp, second_stamp, final_stamp = 200, 260, 320
        with (patch("domain_checks.api_contract_phase.route_domain_telegram_alert", notice),
              patch("domain_checks.api_contract_phase.send_telegram_message", recovery)):
            for stamp in (first_stamp, second_stamp, final_stamp):
                with patch("domain_checks.api_contract_phase.time.time", return_value=stamp):
                    await phase.run(frame)
                if stamp == first_stamp:
                    require(condition=phase.state.last_ok == {"active.invalid": False, "muted.invalid": False},
                            message="down edge lost")
                    healthy = True
                if stamp == second_stamp:
                    require(condition=not phase.state.last_ok["active.invalid"], message="early recovery")
        require(condition=phase.state.last_ok == {"active.invalid": True, "muted.invalid": True},
                message="recovery lost")
        require(condition=calls == ["active.invalid", "muted.invalid"] * 3, message="probe ordering changed")
        kinds = [entry["kind"] for entry in events]
        require(condition=kinds == ["api_contract_degraded"] * 2 + ["api_contract_recovered"] * 2,
                message="event ordering changed")
        require(condition=(notice.await_count, recovery.await_count) == (2, 1), message="routing changed")
        require(condition=events[1]["telegram_alert"] is False, message="muted domain became alertable")

    @staticmethod
    async def test_cancellation_preserves_attempt_timestamps_without_health() -> None:
        """Cancellation at an actual probe await must not become recovery or reset time."""
        phase, frame, events = fixture(AsyncMock(side_effect=asyncio.CancelledError))
        with patch("domain_checks.api_contract_phase.time.time", return_value=200):
            outcome = await asyncio.gather(phase.run(frame), return_exceptions=True)
        require(condition=isinstance(outcome[0], asyncio.CancelledError), message="cancelled probe suppressed")
        require(condition=phase.state.last_run_ts == {"active.invalid": 200, "muted.invalid": 200},
                message="attempt timestamp reset")
        require(condition=not events and not phase.state.last_ok, message="cancellation invented health")

    @staticmethod
    async def test_transport_failure_leaves_recorded_down_state() -> None:
        """A failed notification cannot undo the transition that preceded it."""
        def observe(inputs: ApiContractCall) -> list[ApiContractCheckResult]:
            return [result(inputs["domain"], healthy=False)]

        phase, frame, events = fixture(AsyncMock(side_effect=observe))
        with (patch("domain_checks.api_contract_phase.time.time", return_value=200),
              patch("domain_checks.api_contract_phase.route_domain_telegram_alert",
                    AsyncMock(side_effect=RuntimeError("synthetic transport")))):
            outcome = await asyncio.gather(phase.run(frame), return_exceptions=True)
        require(condition=isinstance(outcome[0], RuntimeError), message="transport failure swallowed")
        require(condition=phase.state.last_ok == {"active.invalid": False}, message="recorded failure lost")
        require(condition=len(events) == 1 and events[0]["kind"] == "api_contract_degraded", message="event lost")
