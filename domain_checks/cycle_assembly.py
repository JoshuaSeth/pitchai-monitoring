# Copyright (c) 2026 PitchAI. All rights reserved.
"""Construct observation phases against the cycle's existing mutable records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .api_contract_phase import ApiContractPhase
from .browser_admission import BrowserConnection
from .container_phase import ContainerPhase
from .cycle_phases import HistoryPhases, MetricPhases
from .dns_phase import DnsPhase
from .domain_result_phase import DomainHealth, DomainResultPhase
from .host_phase import HostPhase
from .meta_phase import MetaPhase
from .performance_phase import PerformancePhase
from .proxy_observation import ProxyReader
from .proxy_phase import ProxyPhase
from .synthetic_phase import SyntheticPhase
from .tls_phase import TlsPhase
from .vitals_phase import VitalsPhase

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from .api_contract_phase import ApiContractCall
    from .browser_probe_contracts import SyntheticProbe, VitalsProbe
    from .common_check import DomainCheckSpec
    from .cycle_channels import CycleChannels
    from .cycle_iteration import CycleParticipants
    from .cycle_persistence import CyclePersistence
    from .cycle_settings import CycleMetricsSettings, CycleProbeSettings, CycleServiceSettings
    from .cycle_startup import CycleLimits
    from .metrics_api_contract import ApiContractCheckResult
    from .signal_history import SignalHistory


@dataclass(frozen=True)
class ObservationSettings:
    """Already decoded options preserve startup validation order."""

    metrics: CycleMetricsSettings
    probes: CycleProbeSettings
    services: CycleServiceSettings


@dataclass(frozen=True)
class NativeProbes[BrowserT: BrowserConnection]:
    """The launcher's actual probe functions, with explicit input contracts."""

    synthetic: SyntheticProbe[BrowserT]
    vitals: VitalsProbe[BrowserT]
    api: Callable[[ApiContractCall], Coroutine[None, None, list[ApiContractCheckResult]]]


@dataclass(frozen=True)
class ObservationPhases[BrowserT: BrowserConnection]:
    """Prepared observations share the owner's health maps and channel objects."""

    metrics: MetricPhases
    history: HistoryPhases
    meta: MetaPhase
    synthetic: SyntheticPhase[BrowserT]
    vitals: VitalsPhase[BrowserT]
    domains: DomainResultPhase


@dataclass(frozen=True)
class PhaseAssembly:
    """Build phases without IO, route allocation or changing observation enablement."""

    settings: ObservationSettings
    persistence: CyclePersistence
    participants: CycleParticipants
    signals: SignalHistory

    def build[BrowserT: BrowserConnection](
        self, channels: CycleChannels, limits: CycleLimits,
        specs: dict[str, DomainCheckSpec], probes: NativeProbes[BrowserT],
    ) -> ObservationPhases[BrowserT]:
        """Return existing phases bound to the same record and configuration references."""
        health = self.persistence.health
        settings = self.settings
        domain_health = DomainHealth(self.persistence.records.domains.last_ok,
                                     self.persistence.records.domains.fail_streak,
                                     self.persistence.records.domains.success_streak, limits.down_after_failures,
                                     limits.up_after_successes)
        domains = DomainResultPhase(domain_health, self.participants.entries, channels, self.persistence.event)
        metrics = self._metrics(channels, specs, probes)
        meta = MetaPhase(settings.services.meta, health.health["meta"])
        synthetic = SyntheticPhase(settings.probes.synthetic, health.probes["synthetic"], probes.synthetic)
        vitals = VitalsPhase(settings.probes.vitals, health.probes["web_vitals"], probes.vitals)
        history = HistoryPhases(settings.metrics.slo, health.health["slo"],
                                settings.metrics.red, health.health["red"])
        return ObservationPhases(metrics, history, meta, synthetic, vitals, domains)

    def _metrics[BrowserT: BrowserConnection](
        self, channels: CycleChannels, specs: dict[str, DomainCheckSpec], probes: NativeProbes[BrowserT],
    ) -> MetricPhases:
        health = self.persistence.health
        settings = self.settings
        host = HostPhase(settings.metrics.host, health.health["host_health"], health.host,
                         channels, self.persistence.event, self.signals)
        performance = PerformancePhase(settings.metrics.performance, health.health["performance"])
        tls = TlsPhase(settings.metrics.tls, health.health["tls"], health.schedules["tls"])
        dns = DnsPhase(settings.metrics.dns, health.health["dns"], health.schedules["dns"], health.dns_ips)
        container = ContainerPhase(settings.services.container, health.health["container_health"],
                                   health.schedules["container_health"], health.containers)
        proxy = ProxyPhase(ProxyReader(settings.services.proxy, self.persistence.dft, specs), health.health["proxy"])
        api = ApiContractPhase(settings.probes.api, health.probes["api_contract"],
                               self.participants.entries, probes.api)
        return MetricPhases(host, performance, tls, dns, api, container, proxy)
