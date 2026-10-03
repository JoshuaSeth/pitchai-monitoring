# Copyright (c) 2026 PitchAI. All rights reserved.
"""Explicit synthetic phase effects verify order and interrupted-cycle boundaries."""

from __future__ import annotations

import asyncio
import unittest
from contextlib import ExitStack
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from .common_check import DomainCheckResult
from .cycle_domain_phase import CycleDomainPhase, DomainCycleObservation
from .cycle_iteration import CycleIteration, CycleParticipants
from .cycle_phases import BrowserPhases, CyclePhases, HistoryPhases, MetricPhases
from .dft_cycle import DftCycle
from .dft_test_support import require
from .health_state import HealthState
from .history_settings import load_red_settings, load_slo_settings
from .resource_settings import load_performance_settings
from .signal_history import SignalHistory
from .test_api_contract_phase import fixture as channels_fixture
from .test_cycle_persistence import fixture as persistence_fixture

if TYPE_CHECKING:
    from .api_contract_phase import ApiContractPhase
    from .browser_admission import BrowserConnection
    from .browser_recovery_phase import BrowserRecoveryPhase
    from .container_phase import ContainerPhase
    from .dns_phase import DnsPhase
    from .heartbeat_phase import HeartbeatPhase
    from .host_phase import HostPhase
    from .meta_phase import MetaPhase
    from .performance_phase import PerformancePhase
    from .proxy_phase import ProxyPhase
    from .synthetic_phase import SyntheticPhase
    from .tls_phase import TlsPhase
    from .vitals_phase import VitalsPhase


def fixture() -> tuple[CycleIteration[BrowserConnection], dict[str, AsyncMock], DomainCycleObservation]:
    """Return local phase mocks referencing real channel/state objects without configured delivery."""
    api, frame, _events = channels_fixture(AsyncMock())
    persistence = persistence_fixture()
    results = {"fixture.invalid": DomainCheckResult("fixture.invalid", ok=True, reason="synthetic", details={})}
    observation = DomainCycleObservation(results, [], [])
    names = ("domains", "slo", "red", "host", "performance", "tls", "dns", "api", "container", "proxy",
             "synthetic", "vitals", "recovery", "heartbeat", "dft", "flush")
    calls = {name: AsyncMock(return_value=None) for name in names}
    calls["domains"].return_value = observation
    calls["host"].return_value = ({}, [])
    calls["performance"].return_value = []
    domains = cast("CycleDomainPhase[BrowserConnection]",
                   MagicMock(spec=CycleDomainPhase, run=calls["domains"], browser=None, retention_seconds=60))
    metrics = MetricPhases(cast("HostPhase", MagicMock(run=calls["host"])),
        cast("PerformancePhase", MagicMock(run=calls["performance"], settings=load_performance_settings({}))),
        cast("TlsPhase", MagicMock(run=calls["tls"])), cast("DnsPhase", MagicMock(run=calls["dns"])),
        cast("ApiContractPhase", MagicMock(run=calls["api"])),
        cast("ContainerPhase", MagicMock(run=calls["container"])), cast("ProxyPhase", MagicMock(run=calls["proxy"])))
    browser = BrowserPhases(cast("SyntheticPhase[BrowserConnection]", MagicMock(run=calls["synthetic"])),
        cast("VitalsPhase[BrowserConnection]", MagicMock(run=calls["vitals"])),
        cast("BrowserRecoveryPhase[BrowserConnection]", MagicMock(run=calls["recovery"])))
    history = HistoryPhases(load_slo_settings({}), HealthState(), load_red_settings({}), HealthState())
    phases = CyclePhases(domains, history, metrics, browser,
                        cast("HeartbeatPhase", MagicMock(run=calls["heartbeat"])), cast("MetaPhase", MagicMock()))
    participants = CycleParticipants(dict(api.entries), frame.domains.alertable)
    return CycleIteration(participants, frame.channels, persistence, phases, SignalHistory({})), calls, observation


class IterationTests(unittest.IsolatedAsyncioTestCase):
    """The real coordinator awaits fake phases; transports never execute."""

    @staticmethod
    async def test_order_and_shared_objects() -> None:
        """All observations precede DFT, pruning, outbox flush and the normal state write."""
        iteration, calls, observation = fixture()
        parent = MagicMock()
        for name, call in calls.items():
            parent.attach_mock(call, name)
        prune = MagicMock()
        persist = MagicMock()
        parent.attach_mock(prune, "prune")
        parent.attach_mock(persist, "persist")
        with ExitStack() as stack:
            stack.enter_context(patch("domain_checks.cycle_iteration.run_slo_phase", calls["slo"]))
            stack.enter_context(patch("domain_checks.cycle_iteration.run_red_phase", calls["red"]))
            stack.enter_context(patch.object(DftCycle, "observe", calls["dft"]))
            stack.enter_context(patch("domain_checks.cycle_persistence.CyclePersistence.flush", calls["flush"]))
            stack.enter_context(patch("domain_checks.cycle_persistence.CyclePersistence.persist", persist))
            stack.enter_context(patch.object(SignalHistory, "prune", prune))
            frame = await iteration.run(100)
        names = [cast("str", call[0]) for call in parent.mock_calls]
        expected = ["domains", "slo", "red", "host", "performance", "tls", "dns", "api", "container", "proxy",
                    "synthetic", "vitals", "recovery", "heartbeat", "dft", "prune", "flush", "persist"]
        require(condition=names == expected, message="phase order changed")
        calls["performance"].assert_awaited_once_with(frame, observation.results)
        calls["proxy"].assert_awaited_once_with(frame, observation.results)
        require(condition=frame.channels is iteration.channels and frame.domains.specs is observation.specs,
                message="shared inputs copied")
        persist.assert_called_once_with("cycle")

    @staticmethod
    async def test_api_cancellation_prevents_later_phases_and_persistence() -> None:
        """An interrupted phase cannot claim heartbeat, DFT or completed state."""
        iteration, calls, _observation = fixture()
        calls["api"].side_effect = asyncio.CancelledError
        with (patch("domain_checks.cycle_iteration.run_slo_phase", calls["slo"]),
              patch("domain_checks.cycle_iteration.run_red_phase", calls["red"]),
              patch("domain_checks.cycle_persistence.CyclePersistence.persist") as persist):
            result = await asyncio.gather(iteration.run(100), return_exceptions=True)
        require(condition=isinstance(result[0], asyncio.CancelledError), message="cancellation suppressed")
        calls["dns"].assert_awaited_once()
        for name in ("container", "proxy", "synthetic", "vitals", "recovery", "heartbeat", "dft", "flush"):
            calls[name].assert_not_awaited()
        persist.assert_not_called()

    @staticmethod
    async def test_failed_domain_phase_prevents_history_and_all_later_observation() -> None:
        """A domain processing error remains an error at the cycle boundary."""
        iteration, calls, _observation = fixture()
        calls["domains"].side_effect = RuntimeError("synthetic domain phase")
        result = await asyncio.gather(iteration.run(100), return_exceptions=True)
        require(condition=isinstance(result[0], RuntimeError), message="domain phase error suppressed")
        for name, call in calls.items():
            if name != "domains":
                call.assert_not_awaited()
