# Copyright (c) 2026 PitchAI. All rights reserved.
"""Host and request-performance settings without host or network observations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .alert_settings import AlertSettings
from .cycle_configuration import cycle_section
from .cycle_values import coerce_float, coerce_optional_float

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .config_values import ConfigValue


@dataclass(frozen=True)
class HostSettings:
    """Optional host thresholds with the original normalized disk-path list."""

    alerts: AlertSettings
    disk_used_percent_max: float | None
    mem_used_percent_max: float | None
    swap_used_percent_max: float | None
    cpu_used_percent_max: float | None
    load1_per_cpu_max: float | None
    disk_paths: list[str]


@dataclass(frozen=True)
class PerformanceSettings:
    """HTTP/browser thresholds and the original mutable per-domain overrides."""

    alerts: AlertSettings
    http_elapsed_ms_max: float
    browser_elapsed_ms_max: float
    overrides: dict[str, ConfigValue] | None


def _disk_paths(raw: ConfigValue) -> list[str]:
    if not isinstance(raw, list) or not raw:
        return ["/"]
    nonempty = [value for value in raw if str(value or "").strip()]
    paths = [str(value).strip() for value in nonempty]
    return paths or ["/"]


def load_host_settings(config: Mapping[str, ConfigValue]) -> HostSettings:
    """Retain optional host thresholds, booleans and the original root fallback.

    Returns:
        Typed configuration only; this function reads no host paths.
    """
    section = cycle_section(config, "host_health")
    return HostSettings(
        alerts=AlertSettings.from_section(section, down=1, up=1),
        disk_used_percent_max=coerce_optional_float(section.get("disk_used_percent_max")),
        mem_used_percent_max=coerce_optional_float(section.get("mem_used_percent_max")),
        swap_used_percent_max=coerce_optional_float(section.get("swap_used_percent_max")),
        cpu_used_percent_max=coerce_optional_float(section.get("cpu_used_percent_max")),
        load1_per_cpu_max=coerce_optional_float(section.get("load1_per_cpu_max")),
        disk_paths=_disk_paths(section.get("disk_paths") or []),
    )


def load_performance_settings(config: Mapping[str, ConfigValue]) -> PerformanceSettings:
    """Retain explicit zero/negative thresholds and caller-owned override maps.

    Returns:
        The existing defaults for unavailable floats, without clamping them.
    """
    section = cycle_section(config, "performance")
    alerts = AlertSettings.from_section(section, down=1, up=1)
    http = coerce_float(section.get("http_elapsed_ms_max", 1500.0), default=1500.0)
    browser = coerce_float(section.get("browser_elapsed_ms_max", 4000.0), default=4000.0)
    overrides = section.get("per_domain_overrides")
    return PerformanceSettings(alerts, http, browser, overrides if isinstance(overrides, dict) else None)
