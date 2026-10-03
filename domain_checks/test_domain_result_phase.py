# Copyright (c) 2026 PitchAI. All rights reserved.
"""Domain transition and dispatch ownership with guarded synthetic transports."""

from __future__ import annotations

import asyncio
import unittest
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from .common_check import DomainCheckResult
from .cycle_channels import CycleChannels
from .dft_test_support import require, require_error
from .dispatch_client import DispatchConfig
from .dispatch_records import DispatchRecords
from .domain_entries import DomainEntryConfig
from .domain_result_phase import DomainHealth, DomainResultPhase
from .inventory import DomainAlertPolicy
from .telegram import TelegramConfig

if TYPE_CHECKING:
    from httpx import AsyncClient

    from .event_bus_delivery import JsonObject


def _fixture(*, muted: bool = False, dispatch: bool = False) -> tuple[DomainResultPhase, list[JsonObject]]:
    events: list[JsonObject] = []

    def event(kind: str, timestamp: float, fields: JsonObject) -> None:
        events.append({"kind": kind, "ts": timestamp, **fields})

    entry = DomainEntryConfig("fixture.invalid", "fixture.invalid",
                              DomainAlertPolicy(telegram="dashboard-only" if muted else "critical",
                                                reason="synthetic policy" if muted else None))
    channels = CycleChannels(cast("AsyncClient", MagicMock()), TelegramConfig("synthetic", "synthetic"),
                             DispatchConfig("https://dispatch.invalid", "synthetic") if dispatch else None,
                             {"enabled": True}, DispatchRecords(), {})
    phase = DomainResultPhase(DomainHealth({}, {}, {}, 2, 2), {entry.domain: entry}, channels, event)
    return phase, events


def _observation(*, healthy: bool = False) -> DomainCheckResult:
    return DomainCheckResult("fixture.invalid", healthy, "synthetic", {"status_code": 200 if healthy else 503})


class TestDomainResults(unittest.IsolatedAsyncioTestCase):
    """Keep health edges, audience policy and failure sequencing observable."""

    @staticmethod
    async def test_debounced_down_and_recovery_keep_input_unchanged() -> None:
        """One downward edge and two-success recovery survive repeated observations."""
        phase, events = _fixture()
        result = _observation()
        route = AsyncMock(return_value=(False, []))
        with patch("domain_checks.domain_result_phase.route_domain_telegram_alert", new=route):
            for healthy in (False, False, False, True, True):
                await phase.observe(_observation(healthy=True) if healthy else result, 100)
        route.assert_awaited_once()
        require(condition=[event["kind"] for event in events] == ["domain_down", "domain_up"],
                message="domain transition count changed")
        require(condition=phase.health.last_ok == {"fixture.invalid": True}, message="recovery state missing")
        require(condition=result.details == {"status_code": 503}, message="enrichment changed input")

    @staticmethod
    async def test_muted_domain_keeps_event_without_transport_or_dispatch() -> None:
        """The real inventory routing boundary suppresses both outgoing paths."""
        phase, events = _fixture(muted=True, dispatch=True)
        send = AsyncMock(side_effect=AssertionError("transport forbidden"))
        dispatch = AsyncMock(side_effect=AssertionError("dispatch forbidden"))
        with (patch("domain_checks.domain_alerts.send_telegram_message_chunked", new=send),
              patch("domain_checks.domain_result_phase.dispatch_and_forward", new=dispatch)):
            await phase.observe(_observation(), 100)
            await phase.observe(_observation(), 101)
        send.assert_not_awaited()
        dispatch.assert_not_awaited()
        require(condition=len(events) == 1 and events[0]["telegram_alert"] is False,
                message="muted domain lost local health evidence")

    @staticmethod
    async def test_warning_exception_preserves_prior_state_and_event() -> None:
        """A failed warning cannot undo the already recorded product observation."""
        phase, events = _fixture(dispatch=True)
        await phase.observe(_observation(), 100)
        with (patch("domain_checks.domain_result_phase.route_domain_telegram_alert",
                    new=AsyncMock(side_effect=OSError("synthetic"))), require_error(OSError, "synthetic")):
            await phase.observe(_observation(), 101)
        require(condition=not phase.health.last_ok["fixture.invalid"] and len(events) == 1,
                message="warning exception rolled back the edge")
        require(condition=not phase.channels.tasks, message="dispatch scheduled after warning exception")

    @staticmethod
    async def test_warning_cancellation_preserves_edge_and_propagates() -> None:
        """Cancellation has the same mutation boundary and is never a recovery."""
        phase, events = _fixture(dispatch=True)
        await phase.observe(_observation(), 100)
        with patch("domain_checks.domain_result_phase.route_domain_telegram_alert",
                   new=AsyncMock(side_effect=asyncio.CancelledError)):
            outcome = await asyncio.gather(phase.observe(_observation(), 101), return_exceptions=True)
        require(condition=isinstance(outcome[0], asyncio.CancelledError) and len(events) == 1,
                message="warning cancellation was swallowed")
        require(condition=not phase.channels.tasks, message="cancelled warning scheduled dispatch")

    @staticmethod
    async def test_unsent_result_keeps_existing_investigation_semantics() -> None:
        """An explicitly unsent local result still reaches the configured dispatch step."""
        phase, events = _fixture(dispatch=True)
        dispatch = AsyncMock()
        with (patch("domain_checks.domain_result_phase.route_domain_telegram_alert",
                    new=AsyncMock(return_value=(False, []))),
              patch("domain_checks.domain_result_phase.dispatch_and_forward", new=dispatch)):
            await phase.observe(_observation(), 100)
            await phase.observe(_observation(), 101)
            await phase.channels.tasks["fixture.invalid"]
        dispatch.assert_awaited_once()
        require(condition=len(events) == 1, message="unsent response altered edge count")

    @staticmethod
    async def test_running_investigation_keeps_task_identity() -> None:
        """A pending investigation is retained even when another DOWN edge occurs."""
        phase, _events = _fixture(dispatch=True)
        pending = asyncio.Event()

        async def hold() -> None:
            await pending.wait()

        task = asyncio.create_task(hold())
        phase.channels.tasks["fixture.invalid"] = task
        dispatch = AsyncMock()
        with (patch("domain_checks.domain_result_phase.route_domain_telegram_alert", new=AsyncMock(return_value=None)),
              patch("domain_checks.domain_result_phase.dispatch_and_forward", new=dispatch)):
            await phase.observe(_observation(), 100)
            await phase.observe(_observation(), 101)
        require(condition=phase.channels.tasks["fixture.invalid"] is task, message="running task replaced")
        dispatch.assert_not_awaited()
        pending.set()
        await task

    @staticmethod
    async def test_unknown_domain_fails_after_counter_update() -> None:
        """Unknown inventory cannot acquire an audience through this phase."""
        phase, events = _fixture()
        result = DomainCheckResult(domain="unknown.invalid", ok=False, reason="synthetic", details={})
        await phase.observe(result, 100)
        with require_error(KeyError, "unknown.invalid"):
            await phase.observe(result, 101)
        require(condition=not phase.health.last_ok["unknown.invalid"] and not events,
                message="unknown domain reordered inventory validation")
