# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed SLO and RED configuration with the existing default rule ownership."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .alert_settings import AlertSettings
from .cycle_configuration import cycle_section
from .cycle_values import coerce_float, coerce_optional_float, required_int

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .event_bus_delivery import JsonValue


@dataclass(frozen=True)
class SloSettings:
    """Availability target and independent short/long burn rule configuration."""

    alerts: AlertSettings
    target_percent: float
    min_total_samples: int
    rules: list[JsonValue]


@dataclass(frozen=True)
class RedSettings:
    """Recorded error-rate and latency thresholds for the original window."""

    alerts: AlertSettings
    window_minutes: int
    min_samples: int
    error_rate_max_percent: float | None
    http_p95_ms_max: float | None
    browser_p95_ms_max: float | None


def load_slo_settings(config: Mapping[str, JsonValue]) -> SloSettings:
    """Load SLO settings, retaining a supplied nonempty rule list by identity.

    Returns:
        Typed settings with new default rule objects only when rules are absent.
    """
    section = cycle_section(config, "slo")
    target = coerce_float(section.get("target_percent", 99.9), default=99.9)
    alerts = AlertSettings.from_section(section, down=3, up=2)
    minimum = max(1, required_int(section.get("min_total_samples", 5)))
    raw_rules = section.get("burn_rate_rules")
    rules: list[JsonValue]
    if not isinstance(raw_rules, list) or not raw_rules:
        rules = [
            {"name": "page_fast_burn", "short_window_minutes": 5, "long_window_minutes": 60,
             "short_burn_rate": 14.4, "long_burn_rate": 6.0},
            {"name": "ticket_slow_burn", "short_window_minutes": 360, "long_window_minutes": 4320,
             "short_burn_rate": 6.0, "long_burn_rate": 1.0},
        ]
    else:
        rules = raw_rules
    return SloSettings(alerts, target, minimum, rules)


def load_red_settings(config: Mapping[str, JsonValue]) -> RedSettings:
    """Read RED's strict sample/window values and optional numeric thresholds.

    Returns:
        The original defaults and optional threshold fallbacks.
    """
    section = cycle_section(config, "red")
    window = max(1, required_int(section.get("window_minutes", 30)))
    minimum = max(1, required_int(section.get("min_samples", 10)))
    error = coerce_optional_float(section.get("error_rate_max_percent"))
    http = coerce_optional_float(section.get("http_p95_ms_max"))
    browser = coerce_optional_float(section.get("browser_p95_ms_max"))
    alerts = AlertSettings.from_section(section, down=3, up=2)
    return RedSettings(alerts, window, minimum, error, http, browser)
