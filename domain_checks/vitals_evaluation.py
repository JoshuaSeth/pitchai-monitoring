# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing optional Web Vitals overrides and independent numeric comparisons."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, cast

from .cycle_values import coerce_optional_float, required_float
from .metrics_web_vitals import WebVitalsResult

if TYPE_CHECKING:
    from .browser_probe_settings import VitalsLimits
    from .common_check import DomainCheckSpec
    from .event_bus_delivery import JsonObject


def thresholds_for(spec: DomainCheckSpec, limits: VitalsLimits) -> dict[str, float | None]:
    """Retain explicit null overrides and the original optional float conversion.

    Returns:
        All three configured thresholds in message-display order.
    """
    # Domain check specifications carry JSON browser configuration.
    value = cast("JsonObject | None", spec.web_vitals)
    config = value if isinstance(value, dict) else {}
    return {"lcp_ms_max": coerce_optional_float(config.get("lcp_ms_max", limits.lcp_ms_max)),
            "cls_max": coerce_optional_float(config.get("cls_max", limits.cls_max)),
            "inp_ms_max": coerce_optional_float(config.get("inp_ms_max", limits.inp_ms_max))}


def evaluate_vitals(result: WebVitalsResult, thresholds: dict[str, float | None]) -> WebVitalsResult:
    """Preserve malformed individual metrics as unavailable, without hiding other violations.

    Returns:
        The same observation unless a successful probe exceeds a usable threshold.
    """
    if not result.ok:
        return result
    metrics = cast("JsonObject", result.metrics or {})
    violations: list[str] = []
    for key, threshold, label, precision in (("lcp_ms", "lcp_ms_max", "lcp_ms", 0),
                                            ("cls", "cls_max", "cls", 3),
                                            ("inp_ms", "inp_ms_max", "inp_ms", 0)):
        value, maximum = metrics.get(key), thresholds[threshold]
        # Browser metric conversion failures originally skip only this comparison.
        with suppress(Exception):
            if maximum is not None and value is not None and required_float(value) > float(maximum):
                violations.append(f"{label}>{float(maximum):.{precision}f}")
    if not violations:
        return result
    return WebVitalsResult(domain=result.domain, ok=False, metrics=result.metrics,
        error="threshold_exceeded: " + ",".join(violations), elapsed_ms=result.elapsed_ms,
        browser_infra_error=result.browser_infra_error)
