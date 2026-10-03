# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing API-contract schedule, debounce and routing settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .alert_settings import AlertSettings
from .cycle_configuration import cycle_section
from .cycle_values import coerce_float, required_int

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .event_bus_delivery import JsonValue


@dataclass(frozen=True)
class ApiContractSettings:
    """Preserve opt-in activation and the original numeric defaults."""

    alerts: AlertSettings
    interval_minutes: int
    timeout_seconds: float

    @classmethod
    def read(cls, config: Mapping[str, JsonValue]) -> ApiContractSettings:
        """Read the current section without adding readiness checks or routes.

        Returns:
            Existing settings decoded in their original error precedence.
        """
        section = cycle_section(config, "api_contract")
        enabled = bool(section.get("enabled", False))
        interval = max(1, required_int(section.get("interval_minutes", 10)))
        timeout = coerce_float(section.get("timeout_seconds", 10.0), default=10.0)
        down = max(1, required_int(section.get("down_after_failures", 2)))
        up = max(1, required_int(section.get("up_after_successes", 2)))
        alerts = AlertSettings(enabled, down, up, bool(section.get("dispatch_on_degraded", False)),
                               bool(section.get("notify_on_recovery", False)))
        return cls(alerts, interval, timeout)
