# Copyright (c) 2026 PitchAI. All rights reserved.
"""Container and monitor-pipeline settings without touching service state."""

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
class ContainerSelection:
    """Preserve configured pattern lists for the existing downstream matcher."""

    monitor_all: bool
    include_patterns: list[ConfigValue]
    exclude_patterns: list[ConfigValue]


@dataclass(frozen=True)
class ContainerSettings:
    """Container inspection transport, schedule and selection policy."""

    alerts: AlertSettings
    interval_minutes: int
    docker_socket_path: str
    timeout_seconds: float
    selection: ContainerSelection


@dataclass(frozen=True)
class MetaSettings:
    """Cycle-overrun and failed-persistence thresholds for pipeline health."""

    alerts: AlertSettings
    cycle_overrun_factor: float
    state_write_failures_max: int


def load_container_settings(config: Mapping[str, ConfigValue]) -> ContainerSettings:
    """Read container settings without opening sockets or normalizing patterns.

    Returns:
        Original defaults and caller-owned include/exclude lists.
    """
    section = cycle_section(config, "container_health")
    interval = max(1, required_int(section.get("interval_minutes", 1)))
    socket = str(section.get("docker_socket_path") or "/var/run/docker.sock").strip()
    include = section.get("include_name_patterns")
    exclude = section.get("exclude_name_patterns")
    timeout = coerce_float(section.get("timeout_seconds", 3.0), default=3.0)
    alerts = AlertSettings.from_section(section, down=2, up=1)
    return ContainerSettings(
        alerts, interval, socket, timeout,
        ContainerSelection(bool(section.get("monitor_all", False)),
                           include if isinstance(include, list) else [], exclude if isinstance(exclude, list) else []),
    )


def load_meta_settings(config: Mapping[str, ConfigValue]) -> MetaSettings:
    """Read pipeline settings while retaining strict write-failure thresholds.

    Returns:
        Existing cycle-overrun fallback and distinct alert defaults.
    """
    section = cycle_section(config, "meta_monitoring")
    factor = coerce_float(section.get("cycle_overrun_factor", 1.25), default=1.25)
    failures = max(1, required_int(section.get("state_write_failures_max", 3)))
    alerts = AlertSettings.from_section(section, down=2, up=2)
    return MetaSettings(alerts, factor, failures)
