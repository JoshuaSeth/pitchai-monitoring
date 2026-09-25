# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tests for test history metrics behavior."""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

import pytest

from domain_checks.history import SampleHistory, append_sample, compute_burn_rate, prune_history, window_samples
from domain_checks.metrics_red import compute_red_violations
from domain_checks.metrics_slo import compute_slo_burn_violations
from domain_checks.testing import verify

if TYPE_CHECKING:
    from domain_checks.history import Sample
    from domain_checks.types import JsonValue

_EXPECTED_HISTORY_SIZE = 3
_EXPECTED_BURN_RATE = 10.0
_SLOW_SAMPLE_COUNT = 25


def test_history_append_and_prune_and_window() -> None:
    """Verify history append and prune and window."""
    h = SampleHistory()
    now = time.time()

    append_sample(h, domain="a", ts=now - 120, ok=True, http_elapsed_ms=10.0, browser_elapsed_ms=None, status_code=200)
    append_sample(h, domain="a", ts=now - 60, ok=False, http_elapsed_ms=20.0, browser_elapsed_ms=None, status_code=502)
    append_sample(h, domain="a", ts=now - 10, ok=True, http_elapsed_ms=30.0, browser_elapsed_ms=None, status_code=200)

    verify("a" in h)
    verify(len(h["a"]) == _EXPECTED_HISTORY_SIZE)

    w = window_samples(h["a"], since_ts=now - 30)
    verify(len(w) == 1)
    verify(bool(w[0][1]) is True)

    prune_history(h, before_ts=now - 30)
    verify(len(h["a"]) == 1)


def test_compute_burn_rate_basic() -> None:
    # SLO 99% => budget=1%. If we have 10% errors, burn=10x.
    """Verify compute burn rate basic."""
    items: list[Sample] = []
    now = time.time()
    for i in range(10):
        ok = i != 0  # 1 failure out of 10 => 10% errors
        items.append((now - i, ok, None, None, None))
    burn = compute_burn_rate(items, slo_target_percent=99.0)
    if burn is None:
        pytest.fail("expected a burn rate for a non-empty valid sample window")
    verify(math.isclose(burn, _EXPECTED_BURN_RATE))


def test_slo_burn_violations_trigger() -> None:
    """Verify slo burn violations trigger."""
    now = time.time()
    h = SampleHistory({"svc": []})

    # 20 samples spanning 20 minutes, 5 failures => high burn.
    for i in range(20):
        ts = now - (i * 60)
        ok = (i % 4) != 0  # 25% errors
        append_sample(h, domain="svc", ts=ts, ok=ok, http_elapsed_ms=None, browser_elapsed_ms=None, status_code=None)

    rules: list[JsonValue] = [
        {
            "name": "test_rule",
            "short_window_minutes": 5,
            "long_window_minutes": 10,
            "short_burn_rate": 1.0,
            "long_burn_rate": 1.0,
        },
    ]
    v = compute_slo_burn_violations(
        history_by_domain=h,
        now_ts=now,
        slo_target_percent=99.9,
        burn_rate_rules=rules,
        min_total_samples=3,
    )
    verify(v)
    verify(v[0].domain == "svc")
    verify(v[0].rule == "test_rule")


def test_red_violations_trigger_on_error_rate_and_latency() -> None:
    """Verify red violations trigger on error rate and latency."""
    now = time.time()
    h = SampleHistory({"svc": []})

    # 30 samples in 30 minutes. Make latencies high and include a few failures.
    for i in range(30):
        ts = now - (i * 60)
        ok = i not in {3, 7, 11}  # 3/30 failures => 10% errors
        http_ms = 5000.0 if i < _SLOW_SAMPLE_COUNT else 10.0  # most samples very slow
        browser_ms = 9000.0
        append_sample(
            h,
            domain="svc",
            ts=ts,
            ok=ok,
            http_elapsed_ms=http_ms,
            browser_elapsed_ms=browser_ms,
            status_code=200,
        )

    v = compute_red_violations(
        history_by_domain=h,
        now_ts=now,
        window_minutes=30,
        min_samples=10,
        error_rate_max_percent=5.0,
        http_p95_ms_max=2000.0,
        browser_p95_ms_max=4000.0,
    )
    verify(v)
    verify(v[0].domain == "svc")
    reason_text = "\n".join(v[0].reasons)
    verify("errors>" in reason_text)
    verify("http_p95>" in reason_text)
    verify("browser_p95>" in reason_text)
