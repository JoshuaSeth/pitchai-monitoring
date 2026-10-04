# Copyright (c) 2026 PitchAI. All rights reserved.
"""Record observed timings with effective health for the existing SLO/RED history."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from .cycle_values import coerce_optional_float, required_int
from .history import append_sample

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .common_check import DomainCheckResult
    from .history_decode import Sample


def record_domain_results(
    history: dict[str, list[Sample]], results: Mapping[str, DomainCheckResult],
    effective: Mapping[str, bool], *, ts: float,
) -> None:
    """Append each result using the debounced state and legacy optional numbers."""
    for domain, result in results.items():
        details = result.details or {}
        http_ms = coerce_optional_float(details.get("http_elapsed_ms"))
        browser_ms = coerce_optional_float(details.get("browser_elapsed_ms"))
        status_code = None
        with suppress(TypeError, ValueError, OverflowError):
            status_code = required_int(details.get("status_code"))
        effective_ok = bool(effective.get(domain, bool(result.ok)))
        append_sample(
            history, domain=domain, ts=float(ts), ok=effective_ok,
            http_elapsed_ms=http_ms, browser_elapsed_ms=browser_ms, status_code=status_code,
        )
