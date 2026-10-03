# Copyright (c) 2026 PitchAI. All rights reserved.
"""Proxy feed and threshold configuration, independent of DFT source selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .alert_settings import AlertSettings
from .cycle_configuration import cycle_section
from .cycle_values import coerce_optional_float, required_int

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .event_bus_delivery import JsonValue


@dataclass(frozen=True)
class ProxyFeedSettings:
    """Original paths, timezone and bounded read-window inputs."""

    access_log_path: str
    error_log_path: str
    timezone_name: str
    window_seconds: int
    access_max_bytes: int
    error_max_bytes: int


@dataclass(frozen=True)
class ProxySettings:
    """Proxy thresholds preserve zero semantics and minimum traffic count."""

    alerts: AlertSettings
    feed: ProxyFeedSettings
    min_total_requests: int
    max_502_504_percent: float | None
    max_upstream_errors_per_domain: int


def load_proxy_settings(config: Mapping[str, JsonValue]) -> ProxySettings:
    """Decode existing shared-feed settings without opening paths or selecting DFT.

    Returns:
        The same paths, byte/window minima and strict numeric failure order.
    """
    section = cycle_section(config, "proxy")
    feed = ProxyFeedSettings(
        access_log_path=str(section.get("access_log_path") or "/var/log/nginx/access.log").strip(),
        error_log_path=str(section.get("error_log_path") or "/var/log/nginx/error.log").strip(),
        timezone_name=str(section.get("timezone") or "Europe/Amsterdam").strip() or "Europe/Amsterdam",
        window_seconds=max(60, required_int(section.get("window_seconds", 300))),
        access_max_bytes=max(10_000, required_int(section.get("access_log_max_bytes", 1_000_000))),
        error_max_bytes=max(10_000, required_int(section.get("error_log_max_bytes", 1_000_000))),
    )
    minimum = max(0, required_int(section.get("min_total_requests", 50)))
    percent = coerce_optional_float(section.get("max_502_504_percent"))
    upstream = max(0, required_int(section.get("max_upstream_errors_per_domain", 5)))
    alerts = AlertSettings.from_section(section, down=2, up=2)
    return ProxySettings(alerts, feed, minimum, percent, upstream)
