# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing startup settings and environment-owned channel configuration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .cycle_configuration import cycle_section
from .cycle_values import coerce_float, required_int
from .dispatch_client import DispatchConfig
from .event_bus import load_event_bus_config
from .heartbeat_phase import ExternalHeartbeat
from .telegram import TelegramConfig

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .event_bus import EventBusConfig
    from .event_bus_delivery import JsonObject, JsonValue

LOGGER = logging.getLogger("service-monitoring")


@dataclass(frozen=True)
class CycleLimits:
    """Configured cadence, concurrency and product debounce without new defaults."""

    interval: int
    tolerance: int
    browser_concurrency: int
    check_concurrency: int
    down_after_failures: int
    up_after_successes: int

    @classmethod
    def read(cls, config: Mapping[str, JsonValue]) -> CycleLimits:
        """Decode required numeric inputs in the original startup order.

        Returns:
            The original interval and minimum-one semaphore/debounce counts.
        """
        interval = required_int(config.get("interval_seconds", 60))
        browser = max(1, required_int(config.get("browser_concurrency", 3)))
        checks = max(1, required_int(config.get("check_concurrency", 25)))
        raw = config.get("alerting") or {}
        alerting = raw if isinstance(raw, dict) else {}
        down = max(1, required_int(alerting.get("down_after_failures", 1)))
        up = max(1, required_int(alerting.get("up_after_successes", 1)))
        return cls(interval, max(120, interval * 2), browser, checks, down, up)


@dataclass(frozen=True)
class ChannelStartup:
    """Use only configured channels; loading does not send or allocate a route."""

    telegram: TelegramConfig = field(repr=False)
    event_bus: EventBusConfig | None = field(repr=False)
    dispatch: DispatchConfig | None = field(repr=False)
    dispatch_state: JsonObject

    @classmethod
    def read(cls, environment: Mapping[str, str]) -> ChannelStartup:
        """Resolve the existing channel configuration and missing-token behavior.

        Returns:
            Validated configuration and the same initial mutable dispatch state.

        Raises:
            RuntimeError: Required Telegram credentials or partial Events config fail validation.
        """
        token = environment.get("TELEGRAM_BOT_TOKEN")
        chat = environment.get("TELEGRAM_CHAT_ID")
        if not token or not chat:
            message = "Missing TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID env vars"
            raise RuntimeError(message)
        telegram = TelegramConfig(bot_token=token, chat_id=chat)
        events = load_event_bus_config(environment)
        if events is None:
            LOGGER.warning("PitchAI Events Bus delivery is not configured")
        else:
            LOGGER.info("PitchAI Events Bus delivery configured environment=%s instance=%s",
                        events.environment, events.instance)
        base = environment.get("PITCHAI_DISPATCH_BASE_URL", "https://dispatch.pitchai.net").strip()
        dispatch_token = environment.get("PITCHAI_DISPATCH_TOKEN")
        model = environment.get("PITCHAI_DISPATCH_MODEL")
        state: JsonObject = {"enabled": True, "disabled_reason": None,
                             "disabled_until_monotonic": None, "last_notify_monotonic": 0.0}
        dispatch: DispatchConfig | None = None
        if dispatch_token and dispatch_token.strip():
            dispatch = DispatchConfig(base_url=base, token=dispatch_token,
                                      model=model.strip() if model and model.strip() else None)
        else:
            LOGGER.warning("Missing PITCHAI_DISPATCH_TOKEN; dispatcher escalation disabled")
            state["enabled"] = False
            state["disabled_reason"] = "missing_token"
        return cls(telegram, events, dispatch, state)


def external_heartbeat(config: Mapping[str, JsonValue], environment: Mapping[str, str]) -> ExternalHeartbeat:
    """Read existing registry precedence without probing it or choosing a new endpoint.

    Returns:
        Existing optional registry settings, retaining empty environment overrides.
    """
    section = cycle_section(config, "external_e2e")
    enabled = bool(section.get("enabled", False))
    base = str(environment.get("E2E_REGISTRY_BASE_URL", str(section.get("base_url") or ""))).strip()
    token = (environment.get("E2E_REGISTRY_MONITOR_TOKEN", "").strip()
             or environment.get("E2E_REGISTRY_ADMIN_TOKEN", "").strip()
             or str(section.get("monitor_token") or "").strip())
    timeout = coerce_float(section.get("timeout_seconds", 8.0), default=8.0)
    return ExternalHeartbeat(enabled, base, token, timeout)
