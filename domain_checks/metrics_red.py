# Copyright (c) 2026 PitchAI. All rights reserved.
"""Threshold comparisons for retained request errors and latency percentiles."""

from __future__ import annotations

from dataclasses import dataclass
from operator import attrgetter
from typing import TYPE_CHECKING, TypedDict, Unpack

from .history import compute_error_rate_percent, latency_percentile_ms, window_samples

if TYPE_CHECKING:
    from .history_decode import Sample


@dataclass(frozen=True)
class RedViolation:
    """Existing per-domain RED outcome, preserving reason order and counts."""

    domain: str
    reasons: list[str]
    total_samples: int
    error_rate_percent: float | None
    http_p95_ms: float | None
    browser_p95_ms: float | None


class RedInputs(TypedDict):
    """Original keyword inputs to the recorded-history RED calculation."""

    history_by_domain: dict[str, list[Sample]]
    now_ts: float
    window_minutes: int
    min_samples: int
    error_rate_max_percent: float | None
    http_p95_ms_max: float | None
    browser_p95_ms_max: float | None


def compute_red_violations(**inputs: Unpack[RedInputs]) -> list[RedViolation]:
    """Evaluate the same original window, minimum count and strict thresholds.

    Returns:
        Violations sorted by domain, with error/HTTP/browser reason ordering.
    """
    cutoff = float(inputs["now_ts"]) - max(1, int(inputs["window_minutes"])) * 60.0
    violations: list[RedViolation] = []
    for domain, items in inputs["history_by_domain"].items():
        window = window_samples(items, since_ts=cutoff)
        if len(window) < max(1, int(inputs["min_samples"])):
            continue
        reasons: list[str] = []
        error = compute_error_rate_percent(window)
        limit = inputs["error_rate_max_percent"]
        if limit is not None and error is not None and float(error) > float(limit):
            reasons.append(f"errors>{float(limit):.2f}%")
        http = latency_percentile_ms(window, field="http_elapsed_ms", percentile=95.0)
        http_limit = inputs["http_p95_ms_max"]
        if http_limit is not None and http is not None and float(http) > float(http_limit):
            reasons.append(f"http_p95>{round(float(http_limit))}ms")
        browser = latency_percentile_ms(window, field="browser_elapsed_ms", percentile=95.0)
        browser_limit = inputs["browser_p95_ms_max"]
        if browser_limit is not None and browser is not None and float(browser) > float(browser_limit):
            reasons.append(f"browser_p95>{round(float(browser_limit))}ms")
        if reasons:
            violations.append(RedViolation(domain, reasons, len(window), error, http, browser))
    violations.sort(key=attrgetter("domain"))
    return violations


class RedDetails(TypedDict):
    """Existing JSON fields, including the caller-owned reasons list."""

    domain: str
    total_samples: int
    error_rate_percent: float | None
    http_p95_ms: float | None
    browser_p95_ms: float | None
    reasons: list[str]


def format_red_violation(entry: RedViolation) -> RedDetails:
    """Return the existing recorded fields without adding raw request data."""
    return {
        "domain": entry.domain, "total_samples": entry.total_samples,
        "error_rate_percent": entry.error_rate_percent, "http_p95_ms": entry.http_p95_ms,
        "browser_p95_ms": entry.browser_p95_ms, "reasons": entry.reasons,
    }
