# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed fixtures for the existing retained-history metric regressions."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, cast

from domain_checks.dft_test_support import require
from domain_checks.history import append_sample, compute_burn_rate, prune_history, window_samples
from domain_checks.metrics_red import compute_red_violations
from domain_checks.metrics_slo import compute_slo_burn_violations

if TYPE_CHECKING:
    from domain_checks.config_values import ConfigValue
    from domain_checks.history_decode import Sample
_INITIAL_SAMPLES = 3
_EXPECTED_BURN = 10.0
_SLOW_SAMPLES = 25


def test_history_append_and_prune_and_window() -> None:
    """Retain append ordering, window selection and pruning assertions."""
    history: dict[str, list[Sample]] = {}
    now = time.time()
    append_sample(
        history, domain="a", ts=now - 120, ok=True, http_elapsed_ms=10.0, browser_elapsed_ms=None, status_code=200,
    )
    append_sample(
        history, domain="a", ts=now - 60, ok=False, http_elapsed_ms=20.0, browser_elapsed_ms=None, status_code=502,
    )
    append_sample(
        history, domain="a", ts=now - 10, ok=True, http_elapsed_ms=30.0, browser_elapsed_ms=None, status_code=200,
    )
    require(condition="a" in history, message="history regression: 'a' in history")
    require(
        condition=len(history["a"]) == _INITIAL_SAMPLES,
        message="history regression: len(history['a']) == _INITIAL_SAMPLES",
    )
    selected = window_samples(history["a"], since_ts=now - 30)
    require(condition=len(selected) == 1, message="history regression: len(selected) == 1")
    require(condition=bool(selected[0][1]) is True, message="history regression: bool(selected[0][1]) is True")
    prune_history(history, before_ts=now - 30)
    require(condition=len(history["a"]) == 1, message="history regression: len(history['a']) == 1")


def test_compute_burn_rate_basic() -> None:
    """Keep the rounded tenfold burn from one failure in ten samples."""
    items: list[Sample] = []
    now = time.time()
    for index in range(10):
        ok = index != 0
        items.append([now - index, ok, None, None, None])
    burn = compute_burn_rate(items, slo_target_percent=99.0)
    require(condition=burn is not None, message="history regression: burn is not None")
    require(
        condition=round(float(cast("float", burn)), 3) == _EXPECTED_BURN,
        message="history regression: round(float(cast('float', burn)), 3) == _EXPECTED_BURN",
    )


def test_slo_burn_violations_trigger() -> None:
    """Retain the original short and long window violation fixture."""
    now = time.time()
    history: dict[str, list[Sample]] = {"svc": []}
    for index in range(20):
        ts = now - index * 60
        ok = index % 4 != 0
        append_sample(
            history, domain="svc", ts=ts, ok=ok, http_elapsed_ms=None, browser_elapsed_ms=None, status_code=None,
        )
    rules: list[ConfigValue] = [
        {
            "name": "test_rule",
            "short_window_minutes": 5,
            "long_window_minutes": 10,
            "short_burn_rate": 1.0,
            "long_burn_rate": 1.0,
        },
    ]
    violations = compute_slo_burn_violations(
        history_by_domain=history, now_ts=now, slo_target_percent=99.9, burn_rate_rules=rules, min_total_samples=3,
    )
    require(condition=bool(violations), message="history regression: violations")
    require(condition=violations[0].domain == "svc", message="history regression: violations[0].domain == 'svc'")
    require(
        condition=violations[0].rule == "test_rule", message="history regression: violations[0].rule == 'test_rule'",
    )


def test_red_violations_trigger_on_error_rate_and_latency() -> None:
    """Keep error and both latency reasons for the original high-latency fixture."""
    now = time.time()
    history: dict[str, list[Sample]] = {"svc": []}
    for index in range(30):
        ts = now - index * 60
        ok = index not in {3, 7, 11}
        http_ms = 5000.0 if index < _SLOW_SAMPLES else 10.0
        browser_ms = 9000.0
        append_sample(
            history, domain="svc", ts=ts, ok=ok, http_elapsed_ms=http_ms,
            browser_elapsed_ms=browser_ms, status_code=200,
        )
    violations = compute_red_violations(
        history_by_domain=history,
        now_ts=now,
        window_minutes=30,
        min_samples=10,
        error_rate_max_percent=5.0,
        http_p95_ms_max=2000.0,
        browser_p95_ms_max=4000.0,
    )
    require(condition=bool(violations), message="history regression: violations")
    require(condition=violations[0].domain == "svc", message="history regression: violations[0].domain == 'svc'")
    error_reason = any("errors>" in reason for reason in violations[0].reasons)
    require(
        condition=error_reason,
        message="history regression: any(('errors>' in reason for reason in violations[0].reasons))",
    )
    http_reason = any("http_p95>" in reason for reason in violations[0].reasons)
    require(
        condition=http_reason,
        message="history regression: any(('http_p95>' in reason for reason in violations[0].reasons))",
    )
    browser_reason = any("browser_p95>" in reason for reason in violations[0].reasons)
    require(
        condition=browser_reason,
        message="history regression: any(('browser_p95>' in reason for reason in violations[0].reasons))",
    )
