# Copyright (c) 2026 PitchAI. All rights reserved.
"""Configuration error order and shared phase ownership, without native IO."""

from __future__ import annotations

import unittest
from contextlib import ExitStack
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from .cycle_assembly import NativeProbes, ObservationSettings, PhaseAssembly
from .cycle_settings import CycleMetricsSettings, CycleProbeSettings, CycleServiceSettings
from .cycle_startup import CycleLimits
from .dft_test_support import require, require_error
from .test_cycle_iteration import fixture as iteration_fixture

if TYPE_CHECKING:
    from .browser_admission import BrowserConnection


class AssemblyTests(unittest.TestCase):
    """Only the existing constructors and mocked option readers execute."""

    @staticmethod
    def test_phase_references_remain_owned_by_the_cycle() -> None:
        """Constructors retain the existing maps, probes and delivery context."""
        iteration, _calls, _observation = iteration_fixture()
        settings = ObservationSettings(CycleMetricsSettings.read({}), CycleProbeSettings.read({}),
                                       CycleServiceSettings.read({}))
        assembly = PhaseAssembly(settings, iteration.persistence, iteration.participants, iteration.signals)
        probes: NativeProbes[BrowserConnection] = NativeProbes(AsyncMock(), AsyncMock(), AsyncMock())
        built = assembly.build(iteration.channels, CycleLimits.read({}), {}, probes)
        state = iteration.persistence
        require(condition=built.domains.health.last_ok is state.records.domains.last_ok, message="domain map copied")
        require(condition=built.domains.channels is iteration.channels, message="channel context copied")
        require(condition=built.metrics.proxy.reader.dft is state.dft, message="DFT authority replaced")
        require(condition=built.metrics.api.state is state.health.probes["api_contract"], message="API state copied")
        require(condition=built.synthetic.probe is probes.synthetic and built.vitals.probe is probes.vitals,
                message="native callbacks replaced")
        require(condition=built.history.slo_health is state.health.health["slo"], message="history health copied")

    @staticmethod
    def test_configuration_validation_keeps_original_order() -> None:
        """A history conversion stays between performance and SLO configuration."""
        parent = MagicMock()
        names = ("load_host_settings", "load_performance_settings", "coerce_float", "load_slo_settings",
                 "load_tls_settings", "load_dns_settings", "load_red_settings")
        with ExitStack() as stack:
            for name in names:
                operation = MagicMock(return_value=7.0 if name == "coerce_float" else None)
                parent.attach_mock(operation, name)
                stack.enter_context(patch("domain_checks.cycle_settings." + name, operation))
            settings = CycleMetricsSettings.read({})
        seen = [cast("str", call[0]) for call in parent.mock_calls]
        require(condition=seen == list(names), message="settings error precedence changed")
        expected_seconds = 7 * 86400
        require(condition=settings.retention_seconds == expected_seconds, message="history age changed")

    @staticmethod
    def test_first_configuration_failure_prevents_later_validation() -> None:
        """Invalid earlier options do not run later configuration readers."""
        with (patch("domain_checks.cycle_settings.load_host_settings", side_effect=ValueError("first field")),
              patch("domain_checks.cycle_settings.load_performance_settings") as performance,
              require_error(ValueError, "first field")):
            CycleMetricsSettings.read({})
        performance.assert_not_called()
