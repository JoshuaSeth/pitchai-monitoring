# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated coverage, scheduling and state ownership at service-phase boundaries."""

from __future__ import annotations

import asyncio
import unittest
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from .common_check import DomainCheckResult, DomainCheckSpec
from .container_phase import ContainerObservations, ContainerPhase
from .cycle_channels import CycleChannels
from .dft_cycle import DftCycle
from .dft_test_support import require
from .dispatch_records import DispatchRecords
from .health_state import HealthState
from .meta_phase import CycleTiming, MetaPhase
from .metrics_nginx import NginxAccessWindowStats
from .probe_frame import ProbeDomains, ProbeFrame, ProbeSchedule
from .proxy_observation import ProxyReader
from .proxy_phase import ProxyPhase
from .proxy_settings import load_proxy_settings
from .service_settings import load_container_settings, load_meta_settings
from .signal_history import SignalHistory
from .telegram import TelegramConfig

if TYPE_CHECKING:
    from httpx import AsyncClient

    from .event_bus_delivery import JsonObject


def _fixture() -> tuple[ProbeFrame, list[JsonObject]]:
    events: list[JsonObject] = []

    def event(kind: str, at: float, fields: JsonObject) -> None:
        events.append({"kind": kind, "ts": at, **fields})

    channels = CycleChannels(cast("AsyncClient", MagicMock()), TelegramConfig("synthetic", "synthetic"),
                             None, {}, DispatchRecords(), {})
    domains = ProbeDomains([DomainCheckSpec("a.invalid", "https://a.invalid")], {"a.invalid"}, {"a.invalid"})
    return ProbeFrame(100, domains, channels, event, SignalHistory({})), events


class TestContainerPhase(unittest.IsolatedAsyncioTestCase):
    """No Docker socket or real transport is available in these tests."""

    @staticmethod
    async def test_failed_inspection_preserves_restart_baseline() -> None:
        """An observation crash advances the attempt and records failure, not empty health."""
        frame, events = _fixture()
        observations = ContainerObservations({"retained": 7})
        before = observations.restart_counts
        settings = load_container_settings({"container_health": {"enabled": True, "down_after_failures": 1}})
        phase = ContainerPhase(settings, HealthState(), ProbeSchedule(), observations)
        with (patch("domain_checks.probe_frame.time.time", return_value=100),
              patch("domain_checks.container_phase.check_container_health", new=AsyncMock(side_effect=OSError)),
              patch("domain_checks.cycle_channels.send_telegram_message_chunked",
                    new=AsyncMock(return_value=(False, [])))):
            issues = await phase.run(frame)
        require(condition=observations.restart_counts is before, message="failed read replaced baseline")
        require(condition=issues is not None and issues[0].error == "container_health_check_crashed",
                message="crash became healthy")
        require(condition=not phase.health.last_ok and events[0]["kind"] == "container_health_degraded",
                message="failure transition missing")

    @staticmethod
    async def test_cancelled_inspection_cannot_change_health() -> None:
        """Cancellation retains the original mapping and no health observation."""
        frame, events = _fixture()
        observations = ContainerObservations({"retained": 7})
        before = observations.restart_counts
        phase = ContainerPhase(load_container_settings({"container_health": {"enabled": True}}),
                               HealthState(), ProbeSchedule(), observations)
        with (patch("domain_checks.probe_frame.time.time", return_value=100),
              patch("domain_checks.container_phase.check_container_health",
                    new=AsyncMock(side_effect=asyncio.CancelledError))):
            outcomes = await asyncio.gather(phase.run(frame), return_exceptions=True)
        require(condition=isinstance(outcomes[0], asyncio.CancelledError), message="cancelled observation suppressed")
        require(condition=phase.health == HealthState() and observations.restart_counts is before and not events,
                message="cancelled read changed state")


class TestProxyPhase(unittest.IsolatedAsyncioTestCase):
    """The existing DFT read owns coverage; no path or journal is opened here."""

    @staticmethod
    async def test_unavailable_coverage_cannot_recover_proxy() -> None:
        """Two healthy reads are required after unavailable coverage, with the same health object."""
        frame, events = _fixture()
        dft = MagicMock(spec=DftCycle)
        dft.coverage_ok = False
        access = MagicMock(return_value=NginxAccessWindowStats(2, 0, 0, 0, []))
        dft.read_access = access
        settings = load_proxy_settings({"proxy": {"enabled": True, "max_502_504_percent": 10,
            "max_upstream_errors_per_domain": 0, "up_after_successes": 2, "notify_on_recovery": False}})
        phase = ProxyPhase(ProxyReader(settings, cast("DftCycle", dft), {}),
                           HealthState(last_ok=False, fail_streak=3))
        results = {"a.invalid": DomainCheckResult(domain="a.invalid", ok=True, reason="ok", details={})}
        await phase.run(frame, results)
        require(condition=not phase.health.last_ok and not events, message="unavailable coverage closed incident")
        dft.coverage_ok = True
        await phase.run(frame, results)
        require(condition=not phase.health.last_ok, message="single read bypassed recovery threshold")
        await phase.run(frame, results)
        require(condition=phase.health.last_ok and events == [{"kind": "proxy_recovered", "ts": 100.0}],
                message="fresh coverage recovery missing")

    @staticmethod
    async def test_disabled_or_empty_cycle_does_not_consume_access() -> None:
        """Skipped proxy work leaves DFT access-coverage ownership untouched."""
        frame, _ = _fixture()
        dft = MagicMock(spec=DftCycle)
        access = MagicMock()
        dft.read_access = access
        settings = load_proxy_settings({"proxy": {"enabled": True, "max_502_504_percent": 10}})
        phase = ProxyPhase(ProxyReader(settings, cast("DftCycle", dft), {}), HealthState())
        await phase.run(frame, {})
        access.assert_not_called()
        disabled = ProxyPhase(ProxyReader(load_proxy_settings({"proxy": {"enabled": False}}),
                                         cast("DftCycle", dft), {}), HealthState())
        results = {"a.invalid": DomainCheckResult(domain="a.invalid", ok=True, reason="ok", details={})}
        await disabled.run(frame, results)
        access.assert_not_called()


class TestMetaPhase(unittest.IsolatedAsyncioTestCase):
    """Pipeline signals preserve thresholds and avoid unnecessary browser calls."""

    @staticmethod
    async def test_exact_overrun_boundary_and_failed_write_threshold() -> None:
        """Equality is healthy for elapsed time, but the configured write count fails."""
        frame, events = _fixture()
        browser = MagicMock()
        connected = MagicMock(side_effect=AssertionError("no dispatch configured"))
        browser.is_connected = connected
        settings = load_meta_settings({"meta_monitoring": {"enabled": True, "down_after_failures": 1,
                                                           "state_write_failures_max": 3}})
        phase = MetaPhase(settings, HealthState())
        timing = CycleTiming(60, 75, 0, browser, 25, 3)
        await phase.run(frame, timing)
        require(condition=phase.health.last_ok and not events, message="exact time boundary failed")
        with patch("domain_checks.cycle_channels.send_telegram_message_chunked",
                   new=AsyncMock(return_value=(False, []))):
            await phase.run(frame, CycleTiming(60, 75, 3, browser, 25, 3))
        require(condition=not phase.health.last_ok and events[0]["reasons"] == ["state_write_failures: streak=3 >= 3"],
                message="write boundary or reason changed")
        connected.assert_not_called()
