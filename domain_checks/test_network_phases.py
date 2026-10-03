# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated scheduling, routing and failure-order regressions for cycle phases."""

from __future__ import annotations

import asyncio
import unittest
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from .common_check import DomainCheckSpec
from .cycle_channels import CycleChannels
from .dft_test_support import require, require_error
from .dispatch_records import DispatchRecords
from .dns_phase import DnsPhase
from .health_state import HealthState
from .metrics_dns import DnsCheckResult
from .metrics_tls import TlsCertCheckResult
from .network_settings import load_dns_settings, load_tls_settings
from .probe_frame import ProbeDomains, ProbeFrame, ProbeSchedule
from .signal_history import SignalHistory
from .telegram import TelegramConfig
from .tls_phase import TlsPhase

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject


def _fixture() -> tuple[ProbeFrame, list[JsonObject]]:
    events: list[JsonObject] = []

    def event(kind: str, stamp: float, fields: JsonObject) -> None:
        events.append({"kind": kind, "ts": stamp, **fields})

    domains = ProbeDomains([DomainCheckSpec("active.invalid", "https://active.invalid")],
                           {"active.invalid", "muted.invalid"}, {"active.invalid"})
    channels = CycleChannels(cast("AsyncClient", MagicMock(spec=AsyncClient)),
                             TelegramConfig("synthetic-unsent", "synthetic"), None, {}, DispatchRecords(), {})
    return ProbeFrame(100, domains, channels, event, SignalHistory({})), events


def _settings() -> JsonObject:
    return {"enabled": True, "interval_minutes": 1, "down_after_failures": 1, "up_after_successes": 2,
            "notify_on_recovery": False, "dispatch_on_degraded": False}


class TestProbeSchedule(unittest.TestCase):
    """Skipped work cannot advance its timestamp or manufacture a fresh sample."""

    @staticmethod
    def test_disabled_does_not_sample_clock() -> None:
        """Disabled scheduling preserves the stored timestamp without a clock read."""
        baseline = 40
        schedule = ProbeSchedule(baseline)
        with patch("domain_checks.probe_frame.time.time", side_effect=AssertionError("clock read")):
            claimed = schedule.claim(enabled=False, has_specs=True, interval_minutes=1)
        require(condition=not claimed and schedule.last_run_ts == baseline, message="disabled schedule changed")

    @staticmethod
    def test_exact_due_boundary_and_empty_inventory() -> None:
        """Equality is due; an empty inventory leaves the attempt unclaimed."""
        baseline = 40
        schedule = ProbeSchedule(baseline)
        with patch("domain_checks.probe_frame.time.time", return_value=100):
            empty = schedule.claim(enabled=True, has_specs=False, interval_minutes=1)
            require(condition=not empty and schedule.last_run_ts == baseline, message="empty inventory advanced")
            claimed = schedule.claim(enabled=True, has_specs=True, interval_minutes=1)
        expected = 100
        require(condition=claimed and schedule.last_run_ts == expected, message="due boundary changed")

    @staticmethod
    def test_not_due_retains_previous_attempt() -> None:
        """An interval one second short cannot create an observation."""
        baseline = 41
        schedule = ProbeSchedule(baseline)
        with patch("domain_checks.probe_frame.time.time", return_value=100):
            claimed = schedule.claim(enabled=True, has_specs=True, interval_minutes=1)
        require(condition=not claimed and schedule.last_run_ts == baseline, message="premature observation")

    @staticmethod
    def test_unknown_failure_and_muted_result_identity() -> None:
        """Unknown global failures remain alertable; muted observations stay untouched."""
        frame, _ = _fixture()
        muted = DnsCheckResult(domain="muted.invalid", ok=False, a_records=[], aaaa_records=[],
                               error="synthetic", drift_detected=False, expected_ips=None)
        unknown = DnsCheckResult(domain="dns", ok=False, a_records=[], aaaa_records=[],
                                 error="synthetic", drift_detected=False, expected_ips=None)
        source = [muted, unknown, unknown]
        result = frame.domains.select(source, "DNS")
        require(condition=result == [unknown, unknown] and result[0] is unknown,
                message="unknown failure or duplicates dropped")
        require(condition=source == [muted, unknown, unknown], message="input list changed")


class TestNetworkPhases(unittest.IsolatedAsyncioTestCase):
    """Probe and transport inputs are replaced; real phase state changes run."""

    @staticmethod
    async def test_dns_failure_then_two_successes() -> None:
        """A probe exception is DOWN; recovery still needs two fresh observations."""
        frame, events = _fixture()
        phase = DnsPhase(load_dns_settings({"dns": _settings()}), HealthState(), ProbeSchedule(), {})
        healthy = DnsCheckResult(domain="active.invalid", ok=True, a_records=["192.0.2.1", "192.0.2.1"],
                                 aaaa_records=[], error=None, drift_detected=False, expected_ips=None)
        with (patch("domain_checks.probe_frame.time.time", return_value=100) as clock,
              patch("domain_checks.dns_phase.check_dns", new=AsyncMock(side_effect=[OSError("synthetic"),
                                                                                  [healthy], [healthy]])),
              patch("domain_checks.cycle_channels.send_telegram_message_chunked",
                    new=AsyncMock(return_value=(False, []))),
              patch("domain_checks.cycle_channels.send_telegram_message", side_effect=AssertionError("outgoing"))):
            failed = await phase.run(frame)
            require(condition=failed is not None and failed[0].error == "dns_check_crashed", message="failure erased")
            require(condition=not phase.health.last_ok and "dns" in phase.last_ips, message="failed state missing")
            clock.return_value = 160
            _ = await phase.run(frame)
            require(condition=not phase.health.last_ok, message="first success recovered early")
            clock.return_value = 220
            _ = await phase.run(frame)
        require(condition=phase.health.last_ok, message="two-success recovery missing")
        require(condition=phase.last_ips["active.invalid"] == ["192.0.2.1"], message="DNS baseline not normalized")
        kinds = [event["kind"] for event in events]
        require(condition=kinds == ["dns_degraded", "dns_recovered"], message="transition order changed")

    @staticmethod
    async def test_tls_cancellation_retains_attempt_without_health() -> None:
        """Cancellation advances the attempted timestamp but cannot invent a result."""
        frame, events = _fixture()
        phase = TlsPhase(load_tls_settings({"tls": _settings()}), HealthState(), ProbeSchedule())
        with (patch("domain_checks.probe_frame.time.time", return_value=100),
              patch("domain_checks.tls_phase.check_tls_certs", new=AsyncMock(side_effect=asyncio.CancelledError))):
            result = await asyncio.gather(phase.run(frame), return_exceptions=True)
        expected = 100
        require(condition=isinstance(result[0], asyncio.CancelledError), message="cancellation hidden")
        require(condition=phase.schedule.last_run_ts == expected and phase.health.last_ok and not events,
                message="cancelled observation altered health")

    @staticmethod
    async def test_tls_warning_failure_retains_transition() -> None:
        """A transport failure retains health, event and schedule from the observation."""
        frame, events = _fixture()
        phase = TlsPhase(load_tls_settings({"tls": _settings()}), HealthState(), ProbeSchedule())
        result = TlsCertCheckResult(domain="active.invalid", ok=False, host=None, port=None,
                                    not_after_iso=None, days_remaining=None, error="synthetic", details={})
        with (patch("domain_checks.probe_frame.time.time", return_value=100),
              patch("domain_checks.tls_phase.check_tls_certs", new=AsyncMock(return_value=[result])),
              patch("domain_checks.cycle_channels.send_telegram_message_chunked",
                    new=AsyncMock(side_effect=OSError("unsent"))), require_error(OSError, "unsent")):
            _ = await phase.run(frame)
        expected = 100
        require(condition=not phase.health.last_ok and phase.schedule.last_run_ts == expected,
                message="send failure undid observation")
        require(condition=events == [{"kind": "tls_degraded", "ts": 100.0,
                                      "failures": 1, "domains": ["active.invalid"]}], message="event changed")
