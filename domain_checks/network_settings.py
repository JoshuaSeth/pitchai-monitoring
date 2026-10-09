# Copyright (c) 2026 PitchAI. All rights reserved.
"""TLS and DNS cycle settings, without resolving hosts or running probes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .alert_settings import AlertSettings
from .cycle_configuration import cycle_section
from .cycle_values import coerce_float, required_int

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .config_values import ConfigValue


@dataclass(frozen=True)
class TlsSettings:
    """Original TLS scheduling, certificate age and transport timeout values."""

    alerts: AlertSettings
    interval_minutes: int
    min_days_valid: float
    timeout_seconds: float


@dataclass(frozen=True)
class DnsDriftSettings:
    """Retain domain drift policy without normalizing its keys or values."""

    alert_on_drift_default: bool
    expected_ips_by_domain: dict[str, ConfigValue]
    alert_on_drift_by_domain: dict[str, ConfigValue]


@dataclass(frozen=True)
class DnsSettings:
    """DNS inputs preserve per-domain map identity until cycle normalization."""

    alerts: AlertSettings
    interval_minutes: int
    timeout_seconds: float
    resolvers: list[str] | None
    require_ipv4: bool
    require_ipv6: bool
    drift: DnsDriftSettings


def load_tls_settings(config: Mapping[str, ConfigValue]) -> TlsSettings:
    """Decode TLS configuration without changing interval or streak minima.

    Returns:
        The existing typed TLS settings, including permissive float fallbacks.
    """
    section = cycle_section(config, "tls")
    interval = max(1, required_int(section.get("interval_minutes", 60)))
    days = coerce_float(section.get("min_days_valid", 14.0), default=14.0)
    timeout = coerce_float(section.get("timeout_seconds", 8.0), default=8.0)
    alerts = AlertSettings.from_section(section, down=2, up=1)
    return TlsSettings(alerts, interval, days, timeout)


def _resolvers(raw: ConfigValue) -> list[str] | None:
    if not isinstance(raw, list):
        return None
    values = [str(value).strip() for value in raw]
    nonempty = [value for value in values if value]
    return nonempty or None


def load_dns_settings(config: Mapping[str, ConfigValue]) -> DnsSettings:
    """Decode DNS settings without interpreting or copying domain policy maps.

    Returns:
        DNS settings with empty resolver lists collapsed to the original None.
    """
    section = cycle_section(config, "dns")
    interval = max(1, required_int(section.get("interval_minutes", 15)))
    timeout = coerce_float(section.get("timeout_seconds", 4.0), default=4.0)
    resolvers = _resolvers(section.get("resolvers"))
    expected = section.get("expected_ips_by_domain")
    drift = section.get("alert_on_drift_by_domain")
    alerts = AlertSettings.from_section(section, down=2, up=1)
    return DnsSettings(
        alerts=alerts, interval_minutes=interval, timeout_seconds=timeout, resolvers=resolvers,
        require_ipv4=bool(section.get("require_ipv4", True)), require_ipv6=bool(section.get("require_ipv6", False)),
        drift=DnsDriftSettings(
            alert_on_drift_default=bool(section.get("alert_on_drift", False)),
            expected_ips_by_domain=expected if isinstance(expected, dict) else {},
            alert_on_drift_by_domain=drift if isinstance(drift, dict) else {},
        ),
    )
