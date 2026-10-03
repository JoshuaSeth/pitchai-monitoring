# Copyright (c) 2026 PitchAI. All rights reserved.
"""Configuration preserves monitor defaults, ownership and failure boundaries."""

from __future__ import annotations

import math
import unittest
from typing import TYPE_CHECKING

from .dft_test_support import require, require_error
from .history_settings import load_red_settings, load_slo_settings
from .network_settings import load_dns_settings, load_tls_settings
from .resource_settings import load_host_settings, load_performance_settings

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject, JsonValue


class MetricSettingsTests(unittest.TestCase):
    """Use synthetic configuration only, without files, observations or delivery."""

    @staticmethod
    def test_defaults_preserve_disabled_metrics_and_distinct_streaks() -> None:
        """Missing sections do not enable metrics or flatten their debounce defaults."""
        settings = [load_host_settings({}), load_performance_settings({}), load_slo_settings({}),
                    load_red_settings({}), load_tls_settings({}), load_dns_settings({})]
        enabled = [item.alerts.enabled for item in settings]
        streaks = [(item.alerts.down_after_failures, item.alerts.up_after_successes) for item in settings]
        routing = [item.alerts.dispatch_on_degraded or item.alerts.notify_on_recovery for item in settings]
        require(condition=not any(enabled), message="metric enabled by default")
        require(condition=streaks == [(1, 1), (1, 1), (3, 2), (3, 2), (2, 1), (2, 1)],
                message="debounce defaults changed")
        require(condition=not any(routing), message="routing flag enabled by default")

    @staticmethod
    def test_optional_thresholds_preserve_zero_negative_and_nonfinite_values() -> None:
        """Absent or malformed optional measurements stay unavailable, never zero."""
        red = load_red_settings({"red": {"error_rate_max_percent": "0", "http_p95_ms_max": [],
                                         "browser_p95_ms_max": -1}})
        require(condition=(red.error_rate_max_percent, red.http_p95_ms_max, red.browser_p95_ms_max) == (0, None, -1),
                message="optional threshold clamped or fabricated")
        perf = load_performance_settings({
            "performance": {"http_elapsed_ms_max": "bad", "browser_elapsed_ms_max": "nan"},
        })
        expected_http = 1500
        require(condition=perf.http_elapsed_ms_max == expected_http and math.isnan(perf.browser_elapsed_ms_max),
                message="permissive float fallback changed")

    @staticmethod
    def test_host_paths_keep_original_falsey_filter_and_root_fallback() -> None:
        """Only host path normalization drops falsey entries before string conversion."""
        host = load_host_settings({"host_health": {"disk_paths": [None, False, 0, "  ", " /synthetic ", True]}})
        require(condition=host.disk_paths == ["/synthetic", "True"], message="path normalization changed")
        cases: list[JsonValue] = [None, [], [0, False, " "], "bad"]
        for raw in cases:
            require(condition=load_host_settings({"host_health": {"disk_paths": raw}}).disk_paths == ["/"],
                    message="root fallback changed")

    @staticmethod
    def test_dns_resolvers_keep_order_duplicates_and_scalar_stringification() -> None:
        """Resolver filtering retains falsey scalar strings and legitimate duplicates."""
        raw: list[JsonValue] = [None, False, 0, " ", " 192.0.2.1 ", "192.0.2.1"]
        dns = load_dns_settings({"dns": {"resolvers": raw}})
        require(condition=dns.resolvers == ["None", "False", "0", "192.0.2.1", "192.0.2.1"],
                message="resolver normalization changed")
        require(condition=raw[4] == " 192.0.2.1 ", message="resolver input mutated")
        require(condition=load_dns_settings({"dns": {"resolvers": [" "]}}).resolvers is None,
                message="empty resolver list did not collapse")

    @staticmethod
    def test_maps_and_supplied_rules_retain_identity() -> None:
        """Settings do not silently clone caller-owned policy maps and rules."""
        expected: JsonObject = {"EXAMPLE.invalid": ["192.0.2.1"]}
        drift: JsonObject = {"EXAMPLE.invalid": "false"}
        overrides: JsonObject = {"EXAMPLE.invalid": {"http_elapsed_ms_max": 0}}
        rules: list[JsonValue] = [{"name": "synthetic"}, None]
        dns = load_dns_settings({"dns": {"expected_ips_by_domain": expected, "alert_on_drift_by_domain": drift}})
        require(condition=dns.drift.expected_ips_by_domain is expected and dns.drift.alert_on_drift_by_domain is drift,
                message="domain policy mapping copied")
        require(condition=load_performance_settings({"performance": {"per_domain_overrides": overrides}}).overrides
                is overrides, message="performance overrides copied")
        require(condition=load_slo_settings({"slo": {"burn_rate_rules": rules}}).rules is rules,
                message="nonempty rule list copied or normalized early")

    @staticmethod
    def test_default_slo_rules_are_independent_between_loads() -> None:
        """Mutating one default list cannot change a later cycle configuration."""
        first = load_slo_settings({})
        second = load_slo_settings({})
        require(condition=first.rules == second.rules and first.rules is not second.rules,
                message="default rules shared across loads")
        require(condition=first.rules[0] is not second.rules[0], message="default rule object shared")
        first.rules.clear()
        expected_rules = 2
        require(condition=len(second.rules) == expected_rules, message="default rule mutation leaked")

    @staticmethod
    def test_truthiness_and_minimum_intervals_are_retained() -> None:
        """Legacy truthy strings remain truthy; numeric minima still clamp to one."""
        tls = load_tls_settings({"tls": {"enabled": "false", "down_after_failures": 0,
                                         "up_after_successes": -2, "interval_minutes": -1,
                                         "dispatch_on_degraded": [1], "notify_on_recovery": "yes"}})
        require(condition=tls.alerts.enabled and tls.alerts.dispatch_on_degraded and tls.alerts.notify_on_recovery,
                message="legacy boolean conversion changed")
        minima = (tls.interval_minutes, tls.alerts.down_after_failures, tls.alerts.up_after_successes)
        require(condition=minima == (1, 1, 1),
                message="required numeric minimum changed")

    @staticmethod
    def test_disabled_invalid_settings_still_fail_in_original_order() -> None:
        """Disabled configuration does not bypass parsing, including competing errors."""
        with require_error(ValueError, "bad"):
            load_tls_settings({"tls": {"enabled": False, "interval_minutes": "bad", "down_after_failures": None}})
        with require_error(TypeError, "NoneType"):
            load_slo_settings({"slo": {"enabled": False, "down_after_failures": None, "min_total_samples": "bad"}})
