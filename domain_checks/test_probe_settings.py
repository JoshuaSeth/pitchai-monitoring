# Copyright (c) 2026 PitchAI. All rights reserved.
"""Probe settings retain scheduling, feed bounds and disabled configuration behavior."""

from __future__ import annotations

import math
import unittest
from datetime import time
from typing import TYPE_CHECKING

from .browser_probe_settings import load_synthetic_settings, load_vitals_settings
from .dft_test_support import require, require_error
from .heartbeat_settings import load_heartbeat_settings
from .proxy_settings import load_proxy_settings
from .service_settings import load_container_settings, load_meta_settings

if TYPE_CHECKING:
    from .event_bus_delivery import JsonValue


class ProbeSettingsTests(unittest.TestCase):
    """All inputs are synthetic and no configured path is opened."""

    @staticmethod
    def test_metrics_default_disabled_with_original_streaks() -> None:
        """Optional probes never become enabled from missing sections."""
        settings = [load_synthetic_settings({}), load_vitals_settings({}), load_container_settings({}),
                    load_proxy_settings({}), load_meta_settings({})]
        enabled = [value.alerts.enabled for value in settings]
        streaks = [(value.alerts.down_after_failures, value.alerts.up_after_successes) for value in settings]
        require(condition=not any(enabled), message="probe enabled by default")
        require(condition=streaks == [(2, 2), (2, 2), (2, 1), (2, 2), (2, 2)], message="debounce defaults changed")

    @staticmethod
    def test_browser_limits_preserve_minima_and_permissive_float_fallbacks() -> None:
        """Counts clamp while optional limits retain zero, negative and nonfinite values."""
        synthetic = load_synthetic_settings({"synthetic": {"interval_minutes": 0, "max_domains_per_cycle": -2,
                                                           "timeout_seconds": "bad"}})
        require(condition=(synthetic.interval_minutes, synthetic.max_domains_per_cycle, synthetic.timeout_seconds)
                == (1, 1, 35.0), message="synthetic schedule defaults changed")
        vitals = load_vitals_settings({"web_vitals": {"post_load_wait_ms": -1, "lcp_ms_max": "nan",
                                                     "cls_max": [], "inp_ms_max": "0"}})
        require(condition=vitals.post_load_wait_ms == -1 and vitals.limits.cls_max is None
                and vitals.limits.inp_ms_max == 0, message="vitals numeric policy changed")
        require(condition=vitals.limits.lcp_ms_max is not None and math.isnan(vitals.limits.lcp_ms_max),
                message="legacy nonfinite limit changed")

    @staticmethod
    def test_proxy_defaults_keep_existing_shared_feed_and_bounds() -> None:
        """Settings alone neither change the authority nor allocate dedicated paths."""
        proxy = load_proxy_settings({})
        require(condition=(proxy.feed.access_log_path, proxy.feed.error_log_path, proxy.feed.timezone_name)
                == ("/var/log/nginx/access.log", "/var/log/nginx/error.log", "Europe/Amsterdam"),
                message="default shared feed changed")
        require(condition=(proxy.feed.window_seconds, proxy.feed.access_max_bytes, proxy.feed.error_max_bytes)
                == (300, 1_000_000, 1_000_000), message="feed defaults changed")

    @staticmethod
    def test_proxy_minima_and_zero_threshold_semantics_are_unchanged() -> None:
        """Window/byte minima remain independent of optional thresholds and traffic count."""
        proxy = load_proxy_settings({"proxy": {"window_seconds": 0, "access_log_max_bytes": -1,
                                               "error_log_max_bytes": "1", "min_total_requests": -1,
                                               "max_upstream_errors_per_domain": 0, "max_502_504_percent": "0"}})
        require(condition=(proxy.feed.window_seconds, proxy.feed.access_max_bytes, proxy.feed.error_max_bytes)
                == (60, 10_000, 10_000), message="feed minimum bounds changed")
        require(condition=(proxy.min_total_requests, proxy.max_upstream_errors_per_domain, proxy.max_502_504_percent)
                == (0, 0, 0), message="zero threshold semantics changed")

    @staticmethod
    def test_whitespace_paths_keep_original_difference_from_absent_paths() -> None:
        """Whitespace disables a path after stripping, while missing paths use defaults."""
        proxy = load_proxy_settings({"proxy": {"access_log_path": " ", "error_log_path": " ", "timezone": " "}})
        require(condition=not proxy.feed.access_log_path and not proxy.feed.error_log_path,
                message="whitespace path replaced by default")
        require(condition=proxy.feed.timezone_name == "Europe/Amsterdam", message="timezone fallback changed")
        container = load_container_settings({"container_health": {"docker_socket_path": " "}})
        require(condition=not container.docker_socket_path, message="whitespace socket path replaced")

    @staticmethod
    def test_container_pattern_lists_retain_identity_and_order() -> None:
        """Existing downstream matching keeps ownership of unnormalized input lists."""
        include: list[JsonValue] = ["^synthetic$", None, "^synthetic$"]
        exclude: list[JsonValue] = ["ignored"]
        settings = load_container_settings({"container_health": {"include_name_patterns": include,
                                                                 "exclude_name_patterns": exclude,
                                                                 "monitor_all": "false"}})
        require(condition=settings.selection.include_patterns is include
                and settings.selection.exclude_patterns is exclude,
                message="patterns copied or normalized")
        require(condition=settings.selection.monitor_all, message="legacy truthiness changed")

    @staticmethod
    def test_disabled_invalid_required_fields_still_fail_in_original_order() -> None:
        """Disabled metrics still parse required bounds and reject competing bad fields."""
        with require_error(ValueError, "bad"):
            load_proxy_settings({"proxy": {"enabled": False, "window_seconds": "bad", "down_after_failures": None}})
        with require_error(TypeError, "NoneType"):
            load_vitals_settings({"web_vitals": {"interval_minutes": None, "max_domains_per_cycle": "bad"}})

    @staticmethod
    def test_heartbeat_keeps_order_duplicates_and_untrimmed_zone_name() -> None:
        """Resolution stays in the cycle; settings retain the original supplied zone text."""
        settings = load_heartbeat_settings({"heartbeat": {"enabled": True, "timezone": " UTC ",
                                                           "times": ["23:59", "00:00", "23:59"]}})
        require(condition=settings.times == [time(23, 59), time(0, 0), time(23, 59)] and settings.timezone == " UTC ",
                message="heartbeat order, duplicate or timezone text changed")

    @staticmethod
    def test_disabled_heartbeat_skips_time_validation_but_enabled_requires_it() -> None:
        """Disabled malformed times are ignored; enabled missing/invalid schedules fail."""
        require(condition=not load_heartbeat_settings({"heartbeat": {"times": ["bad"]}}).times,
                message="disabled schedule was parsed")
        with require_error(ValueError, "non-empty list"):
            load_heartbeat_settings({"heartbeat": {"enabled": True, "times": []}})
        with require_error(ValueError, "Invalid time"):
            load_heartbeat_settings({"heartbeat": {"enabled": True, "times": ["24:00"]}})

    @staticmethod
    def test_meta_defaults_and_required_failure_limit_are_preserved() -> None:
        """Overrun fallback and the write-failure minimum do not disable detection."""
        settings = load_meta_settings({"meta_monitoring": {"cycle_overrun_factor": [], "state_write_failures_max": 0}})
        require(condition=(settings.cycle_overrun_factor, settings.state_write_failures_max) == (1.25, 1),
                message="meta detection defaults changed")
