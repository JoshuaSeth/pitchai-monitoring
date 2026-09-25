# Copyright (c) 2026 PitchAI. All rights reserved.
"""Validated runtime settings for the service monitor."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from domain_checks.common_check import find_chromium_executable
from domain_checks.dispatch_client import DispatchConfig
from domain_checks.event_bus import load_event_bus_config
from domain_checks.inventory import validate_domain_inventory
from domain_checks.monitor_domains import (
    load_config,
    load_domain_spec,
    normalize_domain_entries,
)
from domain_checks.monitor_values import float_value, int_value, json_array, object_config
from domain_checks.telegram import TelegramConfig

if TYPE_CHECKING:
    from domain_checks.common_check import DomainCheckSpec
    from domain_checks.event_bus import EventBusConfig
    from domain_checks.monitor_domains import DomainEntryConfig
    from domain_checks.types import JsonObject

LOGGER = logging.getLogger("service-monitoring")


@dataclass(frozen=True)
class FeaturePolicy:
    """Shared debounce, cadence, recovery, and dispatch policy."""

    enabled: bool
    interval_seconds: int
    down_after_failures: int
    up_after_successes: int
    dispatch_on_degraded: bool
    notify_on_recovery: bool
    options: JsonObject


@dataclass(frozen=True)
class MonitorCorePolicy:
    """Global monitor cadence, concurrency, debounce, and retention policy."""

    interval_seconds: int
    browser_concurrency: int
    check_concurrency: int
    down_after_failures: int
    up_after_successes: int
    history_retention_seconds: float
    browser_min_mem_available_mb: int


@dataclass(frozen=True)
class MonitorInventory:
    """Validated domain inventory and loaded check contracts."""

    entries: list[DomainEntryConfig]
    entries_by_domain: dict[str, DomainEntryConfig]
    specs_by_domain: dict[str, DomainCheckSpec]


@dataclass(frozen=True)
class MonitorConnections:
    """Validated external connection settings and dispatcher state."""

    telegram: TelegramConfig
    dispatch: DispatchConfig | None
    event_bus: EventBusConfig | None
    dispatch_state: JsonObject


@dataclass(frozen=True)
class MonitorSettings:
    """Complete validated monitor settings and inventory."""

    config: JsonObject
    core: MonitorCorePolicy
    inventory: MonitorInventory
    connections: MonitorConnections
    chromium_path: str
    state_path: Path | None
    features: dict[str, FeaturePolicy]

    def feature(self, name: str) -> FeaturePolicy:
        """Return a required configured feature policy.

        Returns:
            The named feature policy.

        Raises:
            RuntimeError: The feature has no configured policy.
        """
        try:
            return self.features[name]
        except KeyError as exc:
            message = f"Unknown monitor feature: {name}"
            raise RuntimeError(message) from exc


_FEATURE_DEFAULTS: dict[str, tuple[int, int, int]] = {
    "host_health": (0, 1, 1),
    "performance": (0, 1, 1),
    "slo": (0, 3, 2),
    "tls": (3600, 2, 1),
    "dns": (900, 2, 1),
    "red": (0, 3, 2),
    "synthetic": (900, 2, 2),
    "web_vitals": (3600, 2, 2),
    "api_contract": (600, 2, 2),
    "container_health": (60, 2, 1),
    "proxy": (0, 2, 2),
    "meta_monitoring": (0, 2, 2),
}


def _feature_policy(config: JsonObject, name: str) -> FeaturePolicy:
    options = object_config(config, name)
    default_interval, default_down, default_up = _FEATURE_DEFAULTS[name]
    interval = default_interval
    if "interval_minutes" in options:
        interval = max(1, int_value(options.get("interval_minutes"), default=default_interval // 60)) * 60
    return FeaturePolicy(
        enabled=bool(options.get("enabled", False)),
        interval_seconds=interval,
        down_after_failures=max(1, int_value(options.get("down_after_failures"), default=default_down)),
        up_after_successes=max(1, int_value(options.get("up_after_successes"), default=default_up)),
        dispatch_on_degraded=bool(options.get("dispatch_on_degraded", False)),
        notify_on_recovery=bool(options.get("notify_on_recovery", False)),
        options=options,
    )


def _telegram_config() -> TelegramConfig:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id:
        return TelegramConfig(bot_token=token, chat_id=chat_id)
    message = "Missing TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID env vars"
    raise RuntimeError(message)


def _dispatch_config() -> tuple[DispatchConfig | None, JsonObject]:
    state: JsonObject = {
        "enabled": True,
        "disabled_reason": None,
        "disabled_until_monotonic": None,
        "last_notify_monotonic": 0.0,
    }
    token = os.getenv("PITCHAI_DISPATCH_TOKEN", "").strip()
    if not token:
        state["enabled"] = False
        state["disabled_reason"] = "missing_token"
        LOGGER.warning("Missing PITCHAI_DISPATCH_TOKEN; dispatcher escalation disabled")
        return None, state
    base_url = os.getenv("PITCHAI_DISPATCH_BASE_URL", "https://dispatch.pitchai.net").strip()
    model_value = os.getenv("PITCHAI_DISPATCH_MODEL", "").strip()
    return DispatchConfig(base_url=base_url, token=token, model=model_value or None), state


def _state_path() -> Path | None:
    value = os.getenv("STATE_PATH", "/data/state.json").strip()
    return Path(value) if value else None


def _domain_inventory(config: JsonObject) -> MonitorInventory:
    domains = json_array(config.get("domains"))
    if not domains:
        message = "Config must contain a non-empty 'domains' list"
        raise ValueError(message)
    entries = normalize_domain_entries(domains)
    specs = {entry.domain: load_domain_spec(entry.raw_entry) for entry in entries}
    entries_by_domain: dict[str, DomainEntryConfig] = {}
    for entry in entries:
        entries_by_domain[entry.domain] = entry
    return MonitorInventory(entries=entries, entries_by_domain=entries_by_domain, specs_by_domain=specs)


def load_settings(config_path: Path) -> MonitorSettings:
    """Load configuration, environment credentials, inventory, and feature policies.

    Returns:
        The complete validated monitor settings.

    Raises:
        RuntimeError: Chromium cannot be located.
    """
    config = load_config(config_path)
    validate_domain_inventory(config)
    inventory = _domain_inventory(config)
    dispatch, dispatch_state = _dispatch_config()
    chromium_path = find_chromium_executable()
    if not chromium_path:
        message = "Could not find a Chromium/Chrome executable (set CHROMIUM_PATH)"
        raise RuntimeError(message)
    history = object_config(config, "history")
    retention_days = max(1.0, float_value(history.get("retention_days"), default=7.0))
    browser_memory = os.getenv("BROWSER_MIN_MEM_AVAILABLE_MB")
    memory_value = browser_memory if browser_memory is not None else config.get("browser_min_mem_available_mb")
    features = {name: _feature_policy(config, name) for name in _FEATURE_DEFAULTS}
    alerting = object_config(config, "alerting")
    interval = int_value(config.get("interval_seconds"), default=60)
    return MonitorSettings(
        config=config,
        core=MonitorCorePolicy(
            interval_seconds=interval,
            browser_concurrency=max(1, int_value(config.get("browser_concurrency"), default=3)),
            check_concurrency=max(1, int_value(config.get("check_concurrency"), default=25)),
            down_after_failures=max(1, int_value(alerting.get("down_after_failures"), default=1)),
            up_after_successes=max(1, int_value(alerting.get("up_after_successes"), default=1)),
            history_retention_seconds=retention_days * 86400.0,
            browser_min_mem_available_mb=max(0, int_value(memory_value, default=2048)),
        ),
        inventory=inventory,
        connections=MonitorConnections(
            telegram=_telegram_config(),
            dispatch=dispatch,
            event_bus=load_event_bus_config(),
            dispatch_state=dispatch_state,
        ),
        chromium_path=chromium_path,
        state_path=_state_path(),
        features=features,
    )
