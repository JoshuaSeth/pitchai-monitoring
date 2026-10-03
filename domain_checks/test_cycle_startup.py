# Copyright (c) 2026 PitchAI. All rights reserved.
"""Startup configuration compatibility with explicit synthetic channel inputs."""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING
from unittest.mock import patch

from .cycle_startup import ChannelStartup, CycleLimits, external_heartbeat
from .dft_test_support import require, require_error
from .dispatch_state import dispatch_is_enabled

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject


class CycleStartupTests(unittest.TestCase):
    """Read configured values without network, route changes or sends."""

    @staticmethod
    def test_limits_keep_cadence_and_minimum_concurrency() -> None:
        """Negative cadence remains unchanged while original minimums still apply."""
        limits = CycleLimits.read({"interval_seconds": "-3", "browser_concurrency": 0,
                                   "check_concurrency": -1, "alerting": {"down_after_failures": "3"}})
        actual = (limits.interval, limits.tolerance, limits.browser_concurrency, limits.check_concurrency,
                  limits.down_after_failures, limits.up_after_successes)
        require(condition=actual == (-3, 120, 1, 1, 3, 1), message="cycle defaults changed")
        with require_error(ValueError, "invalid literal"):
            _ = CycleLimits.read({"interval_seconds": "bad", "browser_concurrency": "also bad"})

    @staticmethod
    def test_missing_telegram_fails_before_reading_events() -> None:
        """A required credential error retains precedence over later configuration."""
        with (patch("domain_checks.cycle_startup.load_event_bus_config") as events,
              require_error(RuntimeError, "Missing TELEGRAM_BOT_TOKEN")):
            _ = ChannelStartup.read({"PITCHAI_MONITORING_EVENT_BUS_URL": "invalid"})
        events.assert_not_called()

    @staticmethod
    def test_missing_dispatch_is_permanently_disabled_without_changing_route() -> None:
        """An absent token cannot create an enabled escalation configuration."""
        channels = ChannelStartup.read({"TELEGRAM_BOT_TOKEN": "synthetic-token", "TELEGRAM_CHAT_ID": "fixture"})
        require(condition=channels.event_bus is None and channels.dispatch is None, message="route was invented")
        require(condition=channels.dispatch_state == {"enabled": False, "disabled_reason": "missing_token",
                "disabled_until_monotonic": None, "last_notify_monotonic": 0.0}, message="stop state changed")
        require(condition=not dispatch_is_enabled(channels.dispatch, channels.dispatch_state),
                message="missing token became enabled")

    @staticmethod
    def test_whitespace_and_enabled_dispatch_keep_original_values() -> None:
        """Only model/base normalization changes whitespace; credential bytes remain exact."""
        channels = ChannelStartup.read({"TELEGRAM_BOT_TOKEN": " synthetic ", "TELEGRAM_CHAT_ID": " fixture ",
                                        "PITCHAI_DISPATCH_BASE_URL": " https://fixture.invalid ",
                                        "PITCHAI_DISPATCH_TOKEN": " token ", "PITCHAI_DISPATCH_MODEL": " model "})
        dispatch = channels.dispatch
        require(condition=dispatch is not None, message="configured dispatch missing")
        actual = (channels.telegram.bot_token, channels.telegram.chat_id,
                  dispatch.base_url if dispatch else None, dispatch.token if dispatch else None,
                  dispatch.model if dispatch else None)
        require(condition=actual == (" synthetic ", " fixture ", "https://fixture.invalid", " token ", "model"),
                message="normalization changed credential bytes")
        require(condition=dispatch_is_enabled(dispatch, channels.dispatch_state), message="configured route disabled")
        require(condition="synthetic" not in repr(channels) and " token " not in repr(channels),
                message="startup representation exposed credentials")

    @staticmethod
    def test_partial_event_configuration_still_fails() -> None:
        """An incomplete receiver cannot silently become a configured route."""
        with require_error(RuntimeError, "Both"):
            _ = ChannelStartup.read({"TELEGRAM_BOT_TOKEN": "synthetic", "TELEGRAM_CHAT_ID": "fixture",
                                     "PITCHAI_MONITORING_EVENT_BUS_URL": "https://events.invalid"})

    @staticmethod
    def test_external_registry_precedence_keeps_explicit_empty_override() -> None:
        """Empty environment base disables its read; tokens keep the existing fallback chain."""
        config: JsonObject = {"external_e2e": {"enabled": True, "base_url": "https://configured.invalid",
                                   "monitor_token": " config-token ", "timeout_seconds": "9"}}
        summary = external_heartbeat(config, {"E2E_REGISTRY_BASE_URL": " ",
                                              "E2E_REGISTRY_MONITOR_TOKEN": " ",
                                              "E2E_REGISTRY_ADMIN_TOKEN": " admin-token "})
        require(condition=(summary.enabled, summary.base_url, summary.token, summary.timeout_seconds)
                == (True, "", "admin-token", 9.0), message="environment precedence changed")

    @staticmethod
    def test_invalid_optional_registry_section_keeps_disabled_defaults() -> None:
        """Unrelated malformed optional input retains the empty-section fallback."""
        summary = external_heartbeat({"external_e2e": ["bad"]}, {})
        require(condition=(summary.enabled, summary.base_url, summary.token, summary.timeout_seconds)
                == (False, "", "", 8.0), message="optional fallback changed")
