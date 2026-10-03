# Copyright (c) 2026 PitchAI. All rights reserved.
"""Heartbeat schedule configuration without clock sampling or delivery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from .cycle_configuration import cycle_section
from .domain_time import parse_hhmm

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import time

    from .config_values import ConfigValue
    from .event_bus_delivery import JsonValue


@dataclass(frozen=True)
class HeartbeatSettings:
    """A configured schedule; timezone resolution stays with the existing cycle."""

    enabled: bool
    timezone: str
    times: list[time]


def load_heartbeat_settings(config: Mapping[str, JsonValue]) -> HeartbeatSettings:
    """Validate enabled schedules while leaving disabled malformed times unused.

    Returns:
        The original ordered time list, including duplicate scheduled times.

    Raises:
        ValueError: Enabled times are absent or an entry is not a valid HH:MM.
    """
    section = cycle_section(config, "heartbeat")
    enabled = bool(section.get("enabled", False))
    timezone = str(section.get("timezone") or "UTC")
    raw = section.get("times") or []
    times: list[time] = []
    if enabled:
        if not isinstance(raw, list) or not raw:
            message = "heartbeat.times must be a non-empty list of HH:MM strings when heartbeat.enabled=true"
            raise ValueError(message)
        times = [parse_hhmm(cast("ConfigValue", value)) for value in raw]
    return HeartbeatSettings(enabled, timezone, times)
