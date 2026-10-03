# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed phase ownership for the existing native monitoring cycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .browser_admission import BrowserConnection

if TYPE_CHECKING:
    from .api_contract_phase import ApiContractPhase
    from .browser_recovery_phase import BrowserRecoveryPhase
    from .container_phase import ContainerPhase
    from .cycle_domain_phase import CycleDomainPhase
    from .dns_phase import DnsPhase
    from .health_state import HealthState
    from .heartbeat_phase import HeartbeatPhase
    from .history_settings import RedSettings, SloSettings
    from .host_phase import HostPhase
    from .meta_phase import MetaPhase
    from .performance_phase import PerformancePhase
    from .proxy_phase import ProxyPhase
    from .synthetic_phase import SyntheticPhase
    from .tls_phase import TlsPhase
    from .vitals_phase import VitalsPhase


@dataclass(frozen=True)
class HistoryPhases:
    """Independent history settings and mutable health shared with persistence."""

    slo_settings: SloSettings
    slo_health: HealthState
    red_settings: RedSettings
    red_health: HealthState


@dataclass(frozen=True)
class MetricPhases:
    """The ordered host, performance, network, API, container and proxy observations."""

    host: HostPhase
    performance: PerformancePhase
    tls: TlsPhase
    dns: DnsPhase
    api: ApiContractPhase
    container: ContainerPhase
    proxy: ProxyPhase


@dataclass(frozen=True)
class BrowserPhases[BrowserT: BrowserConnection]:
    """Browser observations and recovery share the same admitted connection."""

    synthetic: SyntheticPhase[BrowserT]
    vitals: VitalsPhase[BrowserT]
    recovery: BrowserRecoveryPhase[BrowserT]


@dataclass(frozen=True)
class CyclePhases[BrowserT: BrowserConnection]:
    """Group current phases without constructing probes or changing enablement."""

    domains: CycleDomainPhase[BrowserT]
    history: HistoryPhases
    metrics: MetricPhases
    browser: BrowserPhases[BrowserT]
    heartbeat: HeartbeatPhase
    meta: MetaPhase
