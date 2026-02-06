from __future__ import annotations

import time

from domain_checks.history import append_sample, compute_burn_rate, prune_history, window_samples
from domain_checks.metrics_red import compute_red_violations
from domain_checks.metrics_slo import compute_slo_burn_violations


def test_history_append_and_prune_and_window() -> None:
    h: dict[str, list[list[object]]] = {}
    now = time.time()

    append_sample(h, domain="a", ts=now - 120, ok=True, http_elapsed_ms=10.0, browser_elapsed_ms=None, status_code=200)
    append_sample(h, domain="a", ts=now - 60, ok=False, http_elapsed_ms=20.0, browser_elapsed_ms=None, status_code=502)
    append_sample(h, domain="a", ts=now - 10, ok=True, http_elapsed_ms=30.0, browser_elapsed_ms=None, status_code=200)

    assert "a" in h
    assert len(h["a"]) == 3

    w = window_samples(h["a"], since_ts=now - 30)
    assert len(w) == 1
    assert bool(w[0][1]) is True

    prune_history(h, before_ts=now - 30)
    assert len(h["a"]) == 1


def test_compute_burn_rate_basic() -> None:
    # SLO 99% => budget=1%. If we have 10% errors, burn=10x.
    items = []
    now = time.time()
    for i in range(10):
        ok = i != 0  # 1 failure out of 10 => 10% errors
        items.append([now - i, ok, None, None, None])
    burn = compute_burn_rate(items, slo_target_percent=99.0)
    assert burn is not None
    assert round(float(burn), 3) == 10.0


def test_slo_burn_violations_trigger() -> None:
    now = time.time()
    h: dict[str, list[list[object]]] = {"svc": []}

    # 20 samples spanning 20 minutes, 5 failures => high burn.
    for i in range(20):
        ts = now - (i * 60)
        ok = (i % 4) != 0  # 25% errors
        append_sample(h, domain="svc", ts=ts, ok=ok, http_elapsed_ms=None, browser_elapsed_ms=None, status_code=None)

    rules = [
        {
            "name": "test_rule",
            "short_window_minutes": 5,
            "long_window_minutes": 10,
            "short_burn_rate": 1.0,
            "long_burn_rate": 1.0,
        }
    ]
    v = compute_slo_burn_violations(
        history_by_domain=h, now_ts=now, slo_target_percent=99.9, burn_rate_rules=rules, min_total_samples=3
    )
    assert v
    assert v[0].domain == "svc"
    assert v[0].rule == "test_rule"


def test_red_violations_trigger_on_error_rate_and_latency() -> None:
    now = time.time()
    h: dict[str, list[list[object]]] = {"svc": []}

    # 30 samples in 30 minutes. Make latencies high and include a few failures.
    for i in range(30):
        ts = now - (i * 60)
        ok = i not in {3, 7, 11}  # 3/30 failures => 10% errors
        http_ms = 5000.0 if i < 25 else 10.0  # most samples very slow
        browser_ms = 9000.0
        append_sample(h, domain="svc", ts=ts, ok=ok, http_elapsed_ms=http_ms, browser_elapsed_ms=browser_ms, status_code=200)

    v = compute_red_violations(
        history_by_domain=h,
        now_ts=now,
        window_minutes=30,
        min_samples=10,
        error_rate_max_percent=5.0,
        http_p95_ms_max=2000.0,
        browser_p95_ms_max=4000.0,
    )
    assert v
    assert v[0].domain == "svc"
    assert any("errors>" in r for r in v[0].reasons)
    assert any("http_p95>" in r for r in v[0].reasons)
    assert any("browser_p95>" in r for r in v[0].reasons)

