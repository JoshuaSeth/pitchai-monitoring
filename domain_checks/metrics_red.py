from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain_checks.history import (
    Sample,
    compute_error_rate_percent,
    latency_percentile_ms,
    window_samples,
)


@dataclass(frozen=True)
class RedViolation:
    domain: str
    reasons: list[str]
    total_samples: int
    error_rate_percent: float | None
    http_p95_ms: float | None
    browser_p95_ms: float | None


def compute_red_violations(
    *,
    history_by_domain: dict[str, list[Sample]],
    now_ts: float,
    window_minutes: int,
    min_samples: int,
    error_rate_max_percent: float | None,
    http_p95_ms_max: float | None,
    browser_p95_ms_max: float | None,
) -> list[RedViolation]:
    now = float(now_ts)
    w_min = max(1, int(window_minutes))
    cutoff = now - (w_min * 60.0)
    violations: list[RedViolation] = []

    for domain, items in history_by_domain.items():
        w = window_samples(items, since_ts=cutoff)
        if len(w) < max(1, int(min_samples)):
            continue

        reasons: list[str] = []
        err_rate = compute_error_rate_percent(w)
        if error_rate_max_percent is not None and err_rate is not None:
            if float(err_rate) > float(error_rate_max_percent):
                reasons.append(f"errors>{float(error_rate_max_percent):.2f}%")

        http_p95 = latency_percentile_ms(w, field="http_elapsed_ms", percentile=95.0)
        if http_p95_ms_max is not None and http_p95 is not None:
            if float(http_p95) > float(http_p95_ms_max):
                reasons.append(f"http_p95>{int(round(float(http_p95_ms_max)))}ms")

        browser_p95 = latency_percentile_ms(w, field="browser_elapsed_ms", percentile=95.0)
        if browser_p95_ms_max is not None and browser_p95 is not None:
            if float(browser_p95) > float(browser_p95_ms_max):
                reasons.append(f"browser_p95>{int(round(float(browser_p95_ms_max)))}ms")

        if reasons:
            violations.append(
                RedViolation(
                    domain=domain,
                    reasons=reasons,
                    total_samples=len(w),
                    error_rate_percent=err_rate,
                    http_p95_ms=http_p95,
                    browser_p95_ms=browser_p95,
                )
            )

    violations.sort(key=lambda v: v.domain)
    return violations


def format_red_violation(entry: RedViolation) -> dict[str, Any]:
    return {
        "domain": entry.domain,
        "total_samples": entry.total_samples,
        "error_rate_percent": entry.error_rate_percent,
        "http_p95_ms": entry.http_p95_ms,
        "browser_p95_ms": entry.browser_p95_ms,
        "reasons": entry.reasons,
    }

