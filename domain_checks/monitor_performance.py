# Copyright (c) 2026 PitchAI. All rights reserved.
"""Per-domain performance threshold evaluation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain_checks.monitor_values import json_float, json_object

if TYPE_CHECKING:
    from domain_checks.common_check import DomainCheckResult
    from domain_checks.types import JsonObject, JsonValue


def _optional_number(value: JsonValue) -> float | None:
    if value is None:
        return None
    try:
        return json_float(value)
    except (TypeError, ValueError):
        return None


def collect_performance_violations(
    results: dict[str, DomainCheckResult],
    *,
    http_elapsed_ms_max: float,
    browser_elapsed_ms_max: float,
    per_domain_overrides: JsonObject | None = None,
) -> list[JsonObject]:
    """Return healthy domains whose measured latency exceeds policy."""
    overrides = per_domain_overrides or {}
    slow: list[JsonObject] = []
    for domain in sorted(results):
        result = results[domain]
        if not result.ok:
            continue
        override = json_object(overrides.get(domain))
        http_max = json_float(override.get("http_elapsed_ms_max", http_elapsed_ms_max))
        browser_max = json_float(override.get("browser_elapsed_ms_max", browser_elapsed_ms_max))
        http_ms = _optional_number(result.details.get("http_elapsed_ms"))
        browser_ms = _optional_number(result.details.get("browser_elapsed_ms"))
        reasons: list[str] = []
        if http_ms is not None and http_ms > http_max:
            reasons.append(f"http>{round(http_max)}ms")
        if browser_ms is not None and browser_ms > browser_max:
            reasons.append(f"browser>{round(browser_max)}ms")
        if reasons:
            slow.append({
                "domain": domain,
                "http_ms": http_ms,
                "http_max_ms": http_max,
                "browser_ms": browser_ms,
                "browser_max_ms": browser_max,
                "reasons": reasons,
            })
    return slow
