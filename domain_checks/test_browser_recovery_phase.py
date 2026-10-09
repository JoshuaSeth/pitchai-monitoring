# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated browser restart ordering, notice persistence and recovery ownership."""

from __future__ import annotations

import asyncio
import math
import unittest
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from .browser_admission import BrowserAdmission
from .browser_recovery_phase import BrowserRecoveryPhase
from .cycle_channels import CycleChannels
from .dft_test_support import require
from .dispatch_records import DispatchRecords
from .probe_frame import ProbeDomains, ProbeFrame
from .signal_history import SignalHistory
from .telegram import TelegramConfig

if TYPE_CHECKING:
    from httpx import AsyncClient

    from .browser_admission import BrowserConnection, BrowserStateValue
    from .event_bus_delivery import JsonObject


def _fixture() -> tuple[BrowserRecoveryPhase[BrowserConnection], ProbeFrame, list[str], list[JsonObject]]:
    order: list[str] = []
    events: list[JsonObject] = []
    state: dict[str, BrowserStateValue] = {"browser_launch_last_error": "synthetic crash"}

    def event(kind: str, ts: float, fields: JsonObject) -> None:
        order.append("event")
        events.append({"kind": kind, "ts": ts, **fields})

    def persist() -> None:
        require(condition=math.isclose(float(state["browser_degraded_last_notice_ts"] or 0), 100),
                message="notice not stamped")
        order.append("persist")

    def close() -> None:
        order.append("close")

    def launch() -> BrowserConnection:
        order.append("launch")
        return cast("BrowserConnection", MagicMock())

    browser = cast("BrowserConnection", MagicMock(close=AsyncMock(side_effect=close)))
    admission: BrowserAdmission[BrowserConnection] = BrowserAdmission(state, AsyncMock(side_effect=launch),
                                                                    dict, browser)
    channels = CycleChannels(cast("AsyncClient", MagicMock()), TelegramConfig("synthetic", "synthetic"),
                             None, {}, DispatchRecords(), {})
    frame = ProbeFrame(99, ProbeDomains([], set(), set()), channels, event, SignalHistory({}))
    return BrowserRecoveryPhase(admission, lambda: "synthetic host", persist), frame, order, events


class TestBrowserRecoveryPhase(unittest.IsolatedAsyncioTestCase):
    """All transports and native browser operations are substituted."""

    @staticmethod
    async def test_notice_event_persist_precede_restart() -> None:
        """An unsent result keeps existing event/write processing without proving delivery."""
        phase, frame, order, events = _fixture()
        old_browser = phase.admission.browser
        with (patch("domain_checks.browser_recovery_phase.time.time", return_value=100),
              patch("domain_checks.browser_recovery_phase.send_telegram_message",
                    new=AsyncMock(return_value=(False, {})))):
            await phase.run(frame, degraded=True)
        require(condition=order == ["event", "persist", "close", "launch"], message="restart ordering changed")
        require(condition=phase.admission.browser is not old_browser, message="new handle not retained")
        require(condition=events[0]["kind"] == "browser_degraded_notice", message="notice event missing")
        require(condition=frame.signals.samples == {"browser": [[99.0, 0, 0, 0]]},
                message="pre-transition browser signal changed")

    @staticmethod
    async def test_close_cancellation_preserves_handle() -> None:
        """Cancellation after persistence cannot release the retained browser handle."""
        phase, frame, order, _ = _fixture()
        browser = cast("BrowserConnection", MagicMock(close=AsyncMock(side_effect=asyncio.CancelledError)))
        phase.admission.browser = browser
        with (patch("domain_checks.browser_recovery_phase.time.time", return_value=100),
              patch("domain_checks.browser_recovery_phase.send_telegram_message",
                    new=AsyncMock(return_value=(False, {})))):
            result = await asyncio.gather(phase.run(frame, degraded=True), return_exceptions=True)
        require(condition=isinstance(result[0], asyncio.CancelledError), message="close cancellation swallowed")
        require(condition=phase.admission.browser is browser and order == ["event", "persist"],
                message="cancelled close lost handle or launched a replacement")

    @staticmethod
    async def test_notice_failure_prevents_restart_and_persistence() -> None:
        """The existing notice timestamp precedes transport but follow-up effects wait for return."""
        phase, frame, order, events = _fixture()
        old_browser = phase.admission.browser
        with (patch("domain_checks.browser_recovery_phase.time.time", return_value=100),
              patch("domain_checks.browser_recovery_phase.send_telegram_message",
                    new=AsyncMock(side_effect=RuntimeError("synthetic transport")))):
            result = await asyncio.gather(phase.run(frame, degraded=True), return_exceptions=True)
        require(condition=isinstance(result[0], RuntimeError), message="notice error swallowed")
        require(condition=not order and not events and phase.admission.browser is old_browser,
                message="failed notice triggered subsequent effects")
        require(condition=math.isclose(float(phase.admission.state["browser_degraded_last_notice_ts"] or 0), 100),
                message="attempt timestamp changed")

    @staticmethod
    async def test_five_healthy_cycles_are_required() -> None:
        """Recovery preserves the last notice and clears only the original active/streak fields."""
        phase, frame, order, events = _fixture()
        phase.admission.state.update(browser_degraded_active=True, browser_degraded_first_seen_ts=1.0,
                                     browser_degraded_last_notice_ts=2.0)
        with patch("domain_checks.browser_recovery_phase.time.time", return_value=100):
            for _ in range(4):
                await phase.run(frame, degraded=False)
            require(condition=not events and bool(phase.admission.state["browser_degraded_active"]),
                    message="premature browser recovery")
            await phase.run(frame, degraded=False)
        require(condition=events == [{"kind": "browser_recovered", "ts": 100}] and order == ["event"],
                message="browser recovery effects changed")
        require(condition=phase.admission.state["browser_degraded_recover_streak"] == 0
                and math.isclose(float(phase.admission.state["browser_degraded_last_notice_ts"] or 0), 2),
                message="recovery reset historical notice")
