# Copyright (c) 2026 PitchAI. All rights reserved.
"""Ordered configuration groups used to assemble the native observation phases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .api_contract_settings import ApiContractSettings
from .browser_probe_settings import load_synthetic_settings, load_vitals_settings
from .cycle_configuration import cycle_section
from .cycle_values import coerce_float
from .history_settings import load_red_settings, load_slo_settings
from .network_settings import load_dns_settings, load_tls_settings
from .proxy_settings import load_proxy_settings
from .resource_settings import load_host_settings, load_performance_settings
from .service_settings import load_container_settings, load_meta_settings

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .browser_probe_settings import SyntheticSettings, VitalsSettings
    from .event_bus_delivery import JsonValue
    from .history_settings import RedSettings, SloSettings
    from .network_settings import DnsSettings, TlsSettings
    from .proxy_settings import ProxySettings
    from .resource_settings import HostSettings, PerformanceSettings
    from .service_settings import ContainerSettings, MetaSettings


@dataclass(frozen=True)
class CycleMetricsSettings:
    """Host/performance/history/network settings in their original validation order."""

    host: HostSettings
    performance: PerformanceSettings
    retention_seconds: float
    slo: SloSettings
    tls: TlsSettings
    dns: DnsSettings
    red: RedSettings

    @classmethod
    def read(cls, config: Mapping[str, JsonValue]) -> CycleMetricsSettings:
        """Return unchanged defaults, coercions and the first failing field."""
        host = load_host_settings(config)
        performance = load_performance_settings(config)
        history = cycle_section(config, "history")
        days = coerce_float(history.get("retention_days", 7.0), default=7.0)
        retained_seconds = max(1.0, float(days)) * 86400.0
        return cls(host, performance, retained_seconds, load_slo_settings(config),
                   load_tls_settings(config), load_dns_settings(config), load_red_settings(config))


@dataclass(frozen=True)
class CycleProbeSettings:
    """Browser and API observation options, still disabled by their existing defaults."""

    synthetic: SyntheticSettings
    vitals: VitalsSettings
    api: ApiContractSettings

    @classmethod
    def read(cls, config: Mapping[str, JsonValue]) -> CycleProbeSettings:
        """Return the original synthetic, vitals, then API configuration."""
        synthetic = load_synthetic_settings(config)
        vitals = load_vitals_settings(config)
        api = ApiContractSettings.read(config)
        return cls(synthetic, vitals, api)


@dataclass(frozen=True)
class CycleServiceSettings:
    """Container, proxy and pipeline options without changing monitor authority."""

    container: ContainerSettings
    proxy: ProxySettings
    meta: MetaSettings

    @classmethod
    def read(cls, config: Mapping[str, JsonValue]) -> CycleServiceSettings:
        """Return original settings with unchanged error precedence."""
        container = load_container_settings(config)
        proxy = load_proxy_settings(config)
        meta = load_meta_settings(config)
        return cls(container, proxy, meta)
