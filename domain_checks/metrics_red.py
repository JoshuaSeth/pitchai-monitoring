# Copyright (c) 2026 PitchAI. All rights reserved.
"""PitchAI domain monitoring support for metrics red."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple, TypedDict, Unpack

from domain_checks.history import (
    compute_error_rate_percent,
    latency_percentile_ms,
    window_samples,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from domain_checks.history import Sample


class RedViolationPayload(TypedDict):
    """Represent a JSON-ready RED violation summary."""

    domain: str
    total_samples: int
    error_rate_percent: float | None
    http_p95_ms: float | None
    browser_p95_ms: float | None
    reasons: list[str]


@dataclass(frozen=True)
class RedViolation:
    """Represent RedViolation."""

    domain: str
    reasons: list[str]
    total_samples: int
    error_rate_percent: float | None
    http_p95_ms: float | None
    browser_p95_ms: float | None


class RedCheckOptions(TypedDict):
    """Keyword controls accepted by RED metric evaluation."""

    now_ts: float
    window_minutes: int
    min_samples: int
    error_rate_max_percent: float | None
    http_p95_ms_max: float | None
    browser_p95_ms_max: float | None


class _RedThresholds(NamedTuple):
    cutoff: float
    min_samples: int
    error_rate_max_percent: float | None
    http_p95_ms_max: float | None
    browser_p95_ms_max: float | None


def compute_red_violations(
    *,
    history_by_domain: Mapping[str, list[Sample]],
    **options: Unpack[RedCheckOptions],
) -> list[RedViolation]:
    """Compute RED violations for domains with enough recent samples.

    Returns:
        Threshold violations ordered by domain.
    """
    thresholds = _RedThresholds(
        cutoff=float(options["now_ts"])
        - (max(1, int(options["window_minutes"])) * 60.0),
        min_samples=max(1, int(options["min_samples"])),
        error_rate_max_percent=options["error_rate_max_percent"],
        http_p95_ms_max=options["http_p95_ms_max"],
        browser_p95_ms_max=options["browser_p95_ms_max"],
    )
    violations: list[RedViolation] = []

    for domain, items in history_by_domain.items():
        violation = _domain_violation(domain, items, thresholds)
        if violation is not None:
            violations.append(violation)

    violations.sort(key=lambda v: v.domain)
    return violations


def _threshold_reason(
    value: float | None,
    maximum: float | None,
    label: str,
) -> str | None:
    if value is None or maximum is None or float(value) <= float(maximum):
        return None
    if label == "errors":
        return f"errors>{float(maximum):.2f}%"
    return f"{label}>{round(float(maximum))}ms"


def _domain_violation(
    domain: str,
    items: list[Sample],
    thresholds: _RedThresholds,
) -> RedViolation | None:
    window = window_samples(items, since_ts=thresholds.cutoff)
    if len(window) < thresholds.min_samples:
        return None
    error_rate = compute_error_rate_percent(window)
    http_p95 = latency_percentile_ms(
        window,
        field="http_elapsed_ms",
        percentile=95.0,
    )
    browser_p95 = latency_percentile_ms(
        window,
        field="browser_elapsed_ms",
        percentile=95.0,
    )
    candidate_reasons = (
        _threshold_reason(
            error_rate,
            thresholds.error_rate_max_percent,
            "errors",
        ),
        _threshold_reason(http_p95, thresholds.http_p95_ms_max, "http_p95"),
        _threshold_reason(
            browser_p95,
            thresholds.browser_p95_ms_max,
            "browser_p95",
        ),
    )
    reasons = [reason for reason in candidate_reasons if reason is not None]
    if not reasons:
        return None
    return RedViolation(
        domain=domain,
        reasons=reasons,
        total_samples=len(window),
        error_rate_percent=error_rate,
        http_p95_ms=http_p95,
        browser_p95_ms=browser_p95,
    )


def format_red_violation(entry: RedViolation) -> RedViolationPayload:
    """Convert a RED violation to a JSON-ready payload.

    Returns:
        The serialized RED violation.
    """
    return {
        "domain": entry.domain,
        "total_samples": entry.total_samples,
        "error_rate_percent": entry.error_rate_percent,
        "http_p95_ms": entry.http_p95_ms,
        "browser_p95_ms": entry.browser_p95_ms,
        "reasons": entry.reasons,
    }
