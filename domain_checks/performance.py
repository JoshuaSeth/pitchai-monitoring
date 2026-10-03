# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing per-domain performance evaluation, separate from delivery."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, cast

from .cycle_values import coerce_optional_float, required_float

if TYPE_CHECKING:
    from .common_check import DomainCheckResult
    from .config_values import ConfigValue
    from .event_bus_delivery import JsonObject, JsonValue


def metric_violation(raw: JsonValue, maximum: float, label: str) -> tuple[float | None, str | None]:
    """Preserve missing measurements and the original threshold-format fallback.

    Returns:
        The measured value and optional existing reason text. An unformattable
        exceeded threshold leaves this metric unavailable, as before.
    """
    value = coerce_optional_float(raw)
    if value is None or not value > maximum:
        return value, None
    if not math.isfinite(maximum):
        return None, None
    return value, f"{label}>{round(maximum)}ms"


def collect_performance_violations(
    results: dict[str, DomainCheckResult],
    *,
    http_elapsed_ms_max: float,
    browser_elapsed_ms_max: float,
    per_domain_overrides: dict[str, ConfigValue] | None = None,
) -> list[JsonObject]:
    """Evaluate healthy domains in stable order using existing strict thresholds.

    Returns:
        JSON entries for domains with one or more exceeded thresholds.
    """
    overrides = per_domain_overrides if isinstance(per_domain_overrides, dict) else {}
    slow: list[JsonObject] = []
    for domain in sorted(results):
        result = results[domain]
        if not result.ok:
            continue
        entry = evaluate_domain(domain, result, overrides.get(domain), (http_elapsed_ms_max, browser_elapsed_ms_max))
        if entry is not None:
            slow.append(entry)
    return slow


def evaluate_domain(
    domain: str,
    result: DomainCheckResult,
    override_value: ConfigValue,
    defaults: tuple[float, float],
) -> JsonObject | None:
    """Resolve one domain's overrides and independent measurements.

    Returns:
        An entry when a measurement exceeds its threshold, otherwise None.
    """
    details = cast("JsonObject", result.details or {})
    override = override_value if isinstance(override_value, dict) else {}
    http_max = required_float(override.get("http_elapsed_ms_max", defaults[0]))
    browser_max = required_float(override.get("browser_elapsed_ms_max", defaults[1]))
    http_ms, http_reason = metric_violation(details.get("http_elapsed_ms"), http_max, "http")
    browser_ms, browser_reason = metric_violation(details.get("browser_elapsed_ms"), browser_max, "browser")
    reasons: list[JsonValue] = []
    if http_reason is not None:
        reasons.append(http_reason)
    if browser_reason is not None:
        reasons.append(browser_reason)
    if not reasons:
        return None
    return {
        "domain": domain,
        "http_ms": http_ms,
        "http_max_ms": http_max,
        "browser_ms": browser_ms,
        "browser_max_ms": browser_max,
        "reasons": reasons,
    }
