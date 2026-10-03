# Copyright (c) 2026 PitchAI. All rights reserved.
"""Synthetic and Web Vitals configuration without starting browser work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .alert_settings import AlertSettings
from .cycle_configuration import cycle_section
from .cycle_values import coerce_float, coerce_int, coerce_optional_float, required_int

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .config_values import ConfigValue


@dataclass(frozen=True)
class SyntheticSettings:
    """Original per-cycle admission count, interval and transaction timeout."""

    alerts: AlertSettings
    interval_minutes: int
    max_domains_per_cycle: int
    timeout_seconds: float


@dataclass(frozen=True)
class VitalsLimits:
    """Optional measurements remain unavailable when conversion fails."""

    lcp_ms_max: float | None
    cls_max: float | None
    inp_ms_max: float | None


@dataclass(frozen=True)
class VitalsSettings:
    """Web Vitals transport and timing settings with independent limits."""

    alerts: AlertSettings
    interval_minutes: int
    max_domains_per_cycle: int
    timeout_seconds: float
    post_load_wait_ms: int
    limits: VitalsLimits


def load_synthetic_settings(config: Mapping[str, ConfigValue]) -> SyntheticSettings:
    """Retain strict interval/count parsing before debounce configuration.

    Returns:
        Existing defaults without enabling or running any transaction.
    """
    section = cycle_section(config, "synthetic")
    interval = max(1, required_int(section.get("interval_minutes", 15)))
    count = max(1, required_int(section.get("max_domains_per_cycle", 1)))
    timeout = coerce_float(section.get("timeout_seconds", 35.0), default=35.0)
    alerts = AlertSettings.from_section(section, down=2, up=2)
    return SyntheticSettings(alerts, interval, count, timeout)


def load_vitals_settings(config: Mapping[str, ConfigValue]) -> VitalsSettings:
    """Read the original timing defaults, optional thresholds and alert policy.

    Returns:
        Typed settings retaining negative waits and optional nonfinite limits.
    """
    section = cycle_section(config, "web_vitals")
    interval = max(1, required_int(section.get("interval_minutes", 60)))
    count = max(1, required_int(section.get("max_domains_per_cycle", 1)))
    timeout = coerce_float(section.get("timeout_seconds", 45.0), default=45.0)
    wait = coerce_int(section.get("post_load_wait_ms", 4500), default=4500)
    limits = VitalsLimits(
        lcp_ms_max=coerce_optional_float(section.get("lcp_ms_max")),
        cls_max=coerce_optional_float(section.get("cls_max")),
        inp_ms_max=coerce_optional_float(section.get("inp_ms_max")),
    )
    alerts = AlertSettings.from_section(section, down=2, up=2)
    return VitalsSettings(alerts, interval, count, timeout, wait, limits)
