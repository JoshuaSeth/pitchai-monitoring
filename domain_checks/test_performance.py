# Copyright (c) 2026 PitchAI. All rights reserved.
"""Performance contract cases without observations or delivery."""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING, cast

from .common_check import DomainCheckResult
from .dft_test_support import require, require_error
from .message_performance import build_performance_alert_message, build_performance_dispatch_prompt, format_ms
from .performance import collect_performance_violations

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject, JsonValue


class PerformanceTests(unittest.TestCase):
    """Exercise independent metrics, override refusal and presentation bounds."""

    @staticmethod
    def test_only_healthy_domains_exceeding_thresholds_are_reported() -> None:
        """Keep strict equality, domain sorting and DOWN exclusion."""
        results = {
            "z.invalid": DomainCheckResult(domain="z.invalid", ok=True, reason="ok", details={"http_elapsed_ms": 1001}),
            "equal.invalid": DomainCheckResult(domain="equal.invalid", ok=True, reason="ok",
                                                details={"http_elapsed_ms": 1000}),
            "down.invalid": DomainCheckResult(domain="down.invalid", ok=False, reason="down",
                                               details={"http_elapsed_ms": 9999}),
            "a.invalid": DomainCheckResult(domain="a.invalid", ok=True, reason="ok",
                                            details={"browser_elapsed_ms": 2001}),
        }
        slow = collect_performance_violations(results, http_elapsed_ms_max=1000, browser_elapsed_ms_max=2000)
        require(condition=[row["domain"] for row in slow] == ["a.invalid", "z.invalid"],
                message="ordering, equality or DOWN exclusion changed")
        require(condition=slow[0]["reasons"] == ["browser>2000ms"] and slow[1]["reasons"] == ["http>1000ms"],
                message="metric-specific reasons changed")

    @staticmethod
    def test_missing_or_malformed_metric_does_not_hide_other_violation() -> None:
        """Retain valid browser evidence beside unavailable HTTP timings."""
        result = DomainCheckResult(domain="a.invalid", ok=True, reason="ok",
                                   details={"http_elapsed_ms": "bad", "browser_elapsed_ms": "2500"})
        slow = collect_performance_violations(
            {result.domain: result}, http_elapsed_ms_max=1000, browser_elapsed_ms_max=2000,
        )
        expected_browser_ms = 2500
        require(condition=slow[0]["http_ms"] is None and slow[0]["browser_ms"] == expected_browser_ms,
                message="malformed independent metric changed valid evidence")
        retained_http = cast("JsonValue", result.details["http_elapsed_ms"])
        require(condition=retained_http == "bad", message="evaluation mutated caller data")

    @staticmethod
    def test_override_is_strict_and_only_applies_to_its_domain() -> None:
        """A configured invalid threshold still fails instead of defaulting."""
        result = DomainCheckResult(domain="a.invalid", ok=True, reason="ok", details={"http_elapsed_ms": 1200})
        results = {result.domain: result}
        slow = collect_performance_violations(results, http_elapsed_ms_max=1000, browser_elapsed_ms_max=2000,
                                              per_domain_overrides={result.domain: {"http_elapsed_ms_max": 1300}})
        require(condition=not slow, message="domain override ignored")
        with require_error(ValueError, "bad"):
            collect_performance_violations(
                results, http_elapsed_ms_max=1000, browser_elapsed_ms_max=2000,
                per_domain_overrides={result.domain: {"http_elapsed_ms_max": "bad"}},
            )

    @staticmethod
    def test_nonfinite_exceeded_threshold_retains_original_fallback() -> None:
        """A legacy unformattable HTTP threshold does not erase browser evidence."""
        result = DomainCheckResult(domain="a.invalid", ok=True, reason="ok",
                                   details={"http_elapsed_ms": 1000, "browser_elapsed_ms": 2001})
        slow = collect_performance_violations({result.domain: result}, http_elapsed_ms_max=float("-inf"),
                                              browser_elapsed_ms_max=2000)
        require(condition=slow[0]["http_ms"] is None and slow[0]["reasons"] == ["browser>2000ms"],
                message="legacy threshold-format fallback changed")

    @staticmethod
    def test_formatting_keeps_missing_nonfinite_and_rounding_behavior() -> None:
        """Display invalid timings as unavailable and preserve round-to-even."""
        values: list[JsonValue] = [None, "bad", float("nan"), float("inf"), "2.5", 3.5, False]
        formatted = [format_ms(value) for value in values]
        require(condition=formatted == ["n/a", "n/a", "n/a", "n/a", "2ms", "4ms", "0ms"],
                message="display rounding or unavailable label changed")

    @staticmethod
    def test_message_limits_and_unicode_are_unchanged() -> None:
        """Warning and diagnostic builders keep their distinct row/reason limits."""
        indices = range(21)
        domains = [f"d{index}.invalid" for index in indices]
        rows: list[JsonObject] = [
            {"domain": domain, "http_ms": 2.5, "browser_ms": None,
             "reasons": ["één", "twee", "drie", "vier", "vijf"]}
            for domain in domains
        ]
        warning = build_performance_alert_message(slow=rows, down_after_failures=2, fail_streak=2)
        request = build_performance_dispatch_prompt(slow=rows)
        require(condition="d11.invalid" in warning and "d12.invalid" not in warning and "één,twee,drie" in warning,
                message="warning bounds changed")
        expected_reasons = "één, twee, drie, vier"
        require(condition="d19.invalid" in request and "d20.invalid" not in request and expected_reasons in request,
                message="diagnostic bounds changed")
        require(condition="Do NOT deploy" in request, message="diagnostic safety text changed")
