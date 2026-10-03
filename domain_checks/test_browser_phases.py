# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated browser phase admission, attempt ownership and recovery semantics."""

from __future__ import annotations

import asyncio
import unittest
from itertools import starmap
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from .browser_phase_context import BrowserPhaseContext, BrowserProbeState
from .browser_probe_settings import VitalsLimits, load_synthetic_settings, load_vitals_settings
from .common_check import DomainCheckSpec
from .cycle_channels import CycleChannels
from .dft_test_support import require
from .dispatch_records import DispatchRecords
from .domain_entries import DomainEntryConfig
from .inventory import DomainAlertPolicy
from .metrics_synthetic import SyntheticTransactionResult
from .metrics_web_vitals import WebVitalsResult
from .probe_frame import ProbeDomains, ProbeFrame
from .signal_history import SignalHistory
from .synthetic_phase import SyntheticPhase
from .telegram import TelegramConfig
from .vitals_evaluation import evaluate_vitals, thresholds_for
from .vitals_phase import VitalsPhase

if TYPE_CHECKING:
    from httpx import AsyncClient

    from .browser_admission import BrowserAdmission, BrowserConnection
    from .event_bus_delivery import JsonObject


def _context() -> tuple[BrowserPhaseContext[BrowserConnection], list[JsonObject]]:
    events: list[JsonObject] = []

    def event(kind: str, at: float, fields: JsonObject) -> None:
        events.append({"kind": kind, "ts": at, **fields})

    spec = DomainCheckSpec("a.invalid", "https://a.invalid", synthetic_transactions=[{"name": "fixture"}])
    entry = DomainEntryConfig(spec.domain, spec.domain, DomainAlertPolicy(telegram="dashboard-only"))
    channels = CycleChannels(cast("AsyncClient", MagicMock()), TelegramConfig("synthetic", "synthetic"),
                             None, {}, DispatchRecords(), {})
    frame = ProbeFrame(500, ProbeDomains([spec], {spec.domain}, set()), channels, event, SignalHistory({}))
    admission = cast("BrowserAdmission[BrowserConnection]", MagicMock(browser=MagicMock()))
    return BrowserPhaseContext(frame, {spec.domain: entry}, admission, degraded=False), events


class TestBrowserPhases(unittest.IsolatedAsyncioTestCase):
    """All observations and transports are synthetic and local."""

    @staticmethod
    async def test_cancellation_retains_attempt_without_observation() -> None:
        """A cancelled browser call updates its attempt but cannot manufacture health."""
        context, events = _context()
        state = BrowserProbeState({}, {}, {}, {})
        phase: SyntheticPhase[BrowserConnection] = SyntheticPhase(
            load_synthetic_settings({"synthetic": {"enabled": True}}), state,
            AsyncMock(side_effect=asyncio.CancelledError))
        with patch("domain_checks.synthetic_phase.time.time", return_value=10000):
            outcome = await asyncio.gather(phase.run(context), return_exceptions=True)
        require(condition=isinstance(outcome[0], asyncio.CancelledError), message="cancellation suppressed")
        require(condition=state.last_run_ts == {"a.invalid": 10000} and not state.last_ok and not events,
                message="cancelled attempt lost timestamp or advanced health")

    @staticmethod
    async def test_infrastructure_failures_retain_distinct_existing_semantics() -> None:
        """Synthetic filters infra failures; Vitals skips its health observation entirely."""
        context, events = _context()
        synthetic = BrowserProbeState({"a.invalid": False}, {"a.invalid": 2}, {}, {})
        vitals = BrowserProbeState({"a.invalid": False}, {"a.invalid": 2}, {}, {})
        settings: JsonObject = {"enabled": True, "up_after_successes": 1}
        transaction = SyntheticTransactionResult(domain="a.invalid", name="fixture", ok=False,
            elapsed_ms=None, error="infra", details={}, browser_infra_error=True)
        vital = WebVitalsResult(domain="a.invalid", ok=False, metrics={}, error="infra",
                                elapsed_ms=None, browser_infra_error=True)
        with (patch("domain_checks.synthetic_phase.time.time", return_value=10000),
              patch("domain_checks.browser_phase_context.send_telegram_message",
                    new=AsyncMock(side_effect=AssertionError("muted route must not send")))):
            synthetic_phase: SyntheticPhase[BrowserConnection] = SyntheticPhase(
                load_synthetic_settings({"synthetic": settings}), synthetic, AsyncMock(return_value=[transaction]))
            vitals_phase: VitalsPhase[BrowserConnection] = VitalsPhase(
                load_vitals_settings({"web_vitals": settings}), vitals, AsyncMock(return_value=vital))
            await synthetic_phase.run(context)
            await vitals_phase.run(context)
        require(condition=synthetic.last_ok["a.invalid"] and not vitals.last_ok["a.invalid"],
                message="browser infrastructure semantics changed")
        require(condition=events == [{"kind": "synthetic_recovered", "ts": 500.0, "domain": "a.invalid"}],
                message="incorrect recovery event")
        require(condition=vitals.last_run_ts == {"a.invalid": 10000} and vitals.fail_streak == {"a.invalid": 2},
                message="skipped Vitals read changed health or lost attempt")

    @staticmethod
    async def test_muted_failure_records_state_without_dispatch() -> None:
        """An inventory-muted domain still degrades but cannot enter dispatch."""
        context, events = _context()
        state = BrowserProbeState({}, {}, {}, {})
        result = WebVitalsResult(domain="a.invalid", ok=False, metrics={}, error="fixture",
                                 elapsed_ms=5, browser_infra_error=False)
        phase: VitalsPhase[BrowserConnection] = VitalsPhase(
            load_vitals_settings({"web_vitals": {"enabled": True, "down_after_failures": 1}}), state,
            AsyncMock(return_value=result))
        send = AsyncMock(side_effect=AssertionError("muted warning must not send"))
        with (patch("domain_checks.vitals_phase.time.time", return_value=10000),
              patch("domain_checks.domain_alerts.send_telegram_message_chunked", new=send)):
            await phase.run(context)
        require(condition=not state.last_ok["a.invalid"] and events[0]["kind"] == "web_vitals_degraded",
                message="muted observation was discarded")
        require(condition=not context.frame.channels.tasks, message="muted failure entered dispatch")
        send.assert_not_awaited()

    @staticmethod
    def test_due_order_and_threshold_conversion() -> None:
        """Inclusive timing keeps stable ordering; invalid metrics do not hide valid violations."""
        domains = ("a.invalid", "b.invalid", "c.invalid")
        urls = [(name, "https://" + name) for name in domains]
        specs = list(starmap(DomainCheckSpec, urls))
        state = BrowserProbeState({}, {}, {}, {"a.invalid": 940, "b.invalid": 900, "c.invalid": 940})
        candidates = state.candidates(specs, 1000, 1)
        require(condition=[spec.domain for spec in candidates] == ["b.invalid", "a.invalid", "c.invalid"],
                message="due order changed")
        thresholds = thresholds_for(specs[0], VitalsLimits(100, 0.1, 200))
        result = WebVitalsResult(domain="a.invalid", ok=True, metrics={"lcp_ms": "broken", "cls": 0.2, "inp_ms": 200},
                                 error=None, elapsed_ms=5, browser_infra_error=False)
        evaluated = evaluate_vitals(result, thresholds)
        require(condition=evaluated.metrics is result.metrics and evaluated.error == "threshold_exceeded: cls>0.100",
                message="metric conversion or threshold identity changed")
