# Copyright (c) 2026 PitchAI. All rights reserved.
"""Synthetic presentation contracts; every builder remains a pure local call."""

from __future__ import annotations

import unittest

from .dft_test_support import require, require_error
from .message_browser import build_synthetic_alert_message, build_web_vitals_alert_message
from .message_container import build_container_health_alert_message
from .message_proxy import build_proxy_alert_message, build_proxy_dispatch_prompt
from .message_slo_red import build_red_alert_message
from .message_templates import build_host_health_dispatch_prompt, build_meta_alert_message, dispatch_read_only_rules
from .message_tls_dns import build_dns_alert_message, build_tls_alert_message, build_tls_dispatch_prompt
from .metrics_container_health import ContainerHealthIssue
from .metrics_dns import DnsCheckResult
from .metrics_nginx import NginxAccessWindowStats
from .metrics_red import RedViolation
from .metrics_synthetic import SyntheticTransactionResult
from .metrics_tls import TlsCertCheckResult
from .metrics_web_vitals import WebVitalsResult


class MessageContractTests(unittest.TestCase):
    """Protect row boundaries, absent evidence, numeric refusal and caller data."""

    @staticmethod
    def test_tls_filters_before_capping_and_keeps_diagnostic_payload() -> None:
        """Healthy checks cannot consume the bounded failing-check prefix."""
        healthy = TlsCertCheckResult(
            domain="healthy.invalid",
            ok=True,
            host=None,
            port=None,
            not_after_iso=None,
            days_remaining=None,
            error=None,
            details={},
        )
        failed = TlsCertCheckResult(
            domain="failed.invalid",
            ok=False,
            host=None,
            port=None,
            not_after_iso=None,
            days_remaining=None,
            error=" expired ",
            details={"subject": (("name", "ação"),)},
        )
        results = [healthy] * 20 + [failed] * 17
        text = build_tls_alert_message(results=results, min_days_valid=7, down_after_failures=2, fail_streak=3)
        expected_rows = 15
        require(condition=text.count("- failed.invalid:") == expected_rows, message="TLS failure prefix changed")
        require(
            condition="healthy.invalid" not in text and "host=?:443 days_remaining=n/a" in text,
            message="missing TLS observations were fabricated",
        )
        prompt = build_tls_dispatch_prompt(results=results, min_days_valid=7)
        require(
            condition='"ação"' in prompt and dispatch_read_only_rules() in prompt,
            message="TLS Unicode/tuple diagnostic or safety rules changed",
        )
        require(condition=results[0] is healthy and results[-1] is failed, message="builder changed caller results")

    @staticmethod
    def test_dns_keeps_drift_and_record_limits() -> None:
        """Existing ordering and independent A/AAAA/expected prefixes remain."""
        result = DnsCheckResult(
            domain="fixture.invalid",
            ok=False,
            a_records=["one", "two", "three", "four", "five"],
            aaaa_records=[],
            error=" timeout ",
            drift_detected=True,
            expected_ips=["expected"],
        )
        text = build_dns_alert_message(results=[result], down_after_failures=1, fail_streak=9)
        require(
            condition=" drift A=[one,two,three,four] AAAA=[-] expected=[expected] error=timeout" in text,
            message="DNS presentation changed",
        )
        require(condition="Debounce:" not in text and "five" not in text, message="DNS bounds changed")

    @staticmethod
    def test_latency_rounding_and_absent_browser_evidence() -> None:
        """Round-to-even remains distinct from an absent sample."""
        row = RedViolation(
            domain="fixture.invalid",
            reasons=[],
            total_samples=20,
            error_rate_percent=None,
            http_p95_ms=12.5,
            browser_p95_ms=None,
        )
        text = build_red_alert_message(violations=[row], window_minutes=5, down_after_failures=1, fail_streak=0)
        require(
            condition="degraded err=n/a http_p95=12ms browser_p95=n/a samples=20" in text,
            message="RED rounding or absent latency changed",
        )
        synthetic = SyntheticTransactionResult(
            domain="fixture.invalid",
            name="step",
            ok=False,
            elapsed_ms=13.5,
            error=None,
            details={"final_url": "https://fixture.invalid/"},
            browser_infra_error=False,
        )
        text = build_synthetic_alert_message(failures=[synthetic], down_after_failures=1, fail_streak=0)
        require(
            condition="transaction_failed (14ms) url=https://fixture.invalid/" in text,
            message="transaction error fallback or URL changed",
        )

    @staticmethod
    def test_vitals_numeric_refusal_is_not_a_healthy_message() -> None:
        """Invalid observed numeric data still fails at formatting conversion."""
        failure = WebVitalsResult(
            domain="fixture.invalid",
            ok=False,
            metrics={"lcp_ms": "invalid"},
            error=None,
            elapsed_ms=None,
            browser_infra_error=False,
        )
        with require_error(ValueError, "invalid"):
            build_web_vitals_alert_message(failures=[failure], thresholds={}, down_after_failures=1, fail_streak=0)
        absent = WebVitalsResult(
            domain="fixture.invalid",
            ok=False,
            metrics={},
            error=" sample absent ",
            elapsed_ms=None,
            browser_infra_error=False,
        )
        text = build_web_vitals_alert_message(
            failures=[absent],
            thresholds={"lcp_ms": None, "cls": 0.1},
            down_after_failures=1,
            fail_streak=0,
        )
        require(
            condition="Thresholds: cls=0.1" in text and "metrics=n/a error=sample absent" in text,
            message="absent vitals became measured data",
        )

    @staticmethod
    def test_container_flags_preserve_order_and_unknown_state() -> None:
        """Unknown running state is not rendered as a confirmed stopped service."""
        issue = ContainerHealthIssue(
            name="synthetic",
            container_id="fixture-id",
            running=False,
            status="exited",
            restart_count=3,
            restart_increase=2,
            oom_killed=True,
            health_status="unhealthy",
            exit_code=7,
            error="fixture",
        )
        unknown = ContainerHealthIssue(
            name="unknown",
            container_id="fixture-unknown",
            running=None,
            status=None,
            restart_count=None,
            restart_increase=None,
            oom_killed=None,
            health_status=None,
            exit_code=None,
            error=None,
        )
        text = build_container_health_alert_message(issues=[issue, unknown], down_after_failures=1, fail_streak=0)
        require(
            condition="NOT_RUNNING,health=unhealthy,OOMKilled,restarted(+2),exit=7,error=fixture" in text,
            message="container failure flags changed",
        )
        require(
            condition="- unknown (fixture-unknown): issue status=None" in text,
            message="unknown container status was invented",
        )

    @staticmethod
    def test_proxy_keeps_count_order_and_content_free_input() -> None:
        """Already sanitized input stays content-free and numeric errors stay loud."""
        stats = NginxAccessWindowStats(total=2, status_5xx=1, status_502_504=1, status_4xx=0, sample_lines=[])
        text = build_proxy_alert_message(
            upstream_issues=[],
            access_stats=stats,
            upstream_errors_summary={"counts_by_server": {"first": "2", "second": 2, "large": 9}},
            window_seconds=300,
            down_after_failures=1,
            fail_streak=0,
        )
        require(
            condition="502/504=1 (50.00%)" in text and "Sample 502/504 lines:" not in text,
            message="proxy counters or sanitized sample handling changed",
        )
        require(
            condition=text.index("- large:") < text.index("- first:") < text.index("- second:"),
            message="proxy count ordering or stable ties changed",
        )
        prompt = build_proxy_dispatch_prompt(
            upstream_issues=[],
            access_stats=stats,
            upstream_error_events=[],
            window_seconds=300,
        )
        require(
            condition='"sample_lines": []' in prompt and not stats.sample_lines,
            message="proxy builder invented samples or mutated input",
        )
        with require_error(ValueError, "invalid"):
            build_proxy_alert_message(
                upstream_issues=[],
                access_stats=None,
                upstream_errors_summary={"counts_by_server": {"bad": "invalid"}},
                window_seconds=300,
                down_after_failures=1,
                fail_streak=0,
            )

    @staticmethod
    def test_monitor_diagnostics_bound_reasons_and_preserve_unicode() -> None:
        """Local diagnostic text carries existing safety rules and bounded lists."""
        text = build_meta_alert_message(
            reasons=[f"issue-{index}" for index in range(14)], down_after_failures=1, fail_streak=0,
        )
        require(condition="issue-11" in text and "issue-12" not in text, message="meta reason prefix changed")
        prompt = build_host_health_dispatch_prompt(violations=[], snap={"label": "ação", "cpu": None})
        require(
            condition="Observed violations:\n(none)" in prompt and '"ação"' in prompt,
            message="empty/Unicode host context changed",
        )
        require(condition=dispatch_read_only_rules() in prompt, message="host diagnostic safety text changed")
