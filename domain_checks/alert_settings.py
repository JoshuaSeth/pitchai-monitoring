# Copyright (c) 2026 PitchAI. All rights reserved.
"""Explicit enablement, debounce and routing settings for metric observations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from .cycle_values import required_int

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .event_bus_delivery import JsonValue


@dataclass(frozen=True)
class AlertSettings:
    """Retain truthiness and required-integer conversion at configuration time."""

    enabled: bool
    down_after_failures: int
    up_after_successes: int
    dispatch_on_degraded: bool
    notify_on_recovery: bool

    @classmethod
    def from_section(cls, section: Mapping[str, JsonValue], *, down: int, up: int) -> Self:
        """Read the existing flags and fail loudly for malformed debounce values.

        Returns:
            Metric-specific defaults with the original minimum streak of one.
        """
        return cls(
            enabled=bool(section.get("enabled", False)),
            down_after_failures=max(1, required_int(section.get("down_after_failures", down))),
            up_after_successes=max(1, required_int(section.get("up_after_successes", up))),
            dispatch_on_degraded=bool(section.get("dispatch_on_degraded", False)),
            notify_on_recovery=bool(section.get("notify_on_recovery", False)),
        )
