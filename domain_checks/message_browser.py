# Copyright (c) 2026 PitchAI. All rights reserved.
"""Pure existing monitor text construction; no delivery or observation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from .cycle_values import required_float
from .message_templates import dispatch_read_only_rules as _dispatch_read_only_rules

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject
    from .metrics_synthetic import SyntheticTransactionResult
    from .metrics_web_vitals import WebVitalsResult


def build_synthetic_alert_message(
    *,
    failures: list[SyntheticTransactionResult],
    down_after_failures: int,
    fail_streak: int,
) -> str:
    """Return the existing bounded message without invoking a transport."""
    lines = ["Monitor warning: Synthetic transactions are failing ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.append("")
    for r in failures[:15]:
        ms = "n/a" if r.elapsed_ms is None else f"{round(float(r.elapsed_ms))}ms"
        err = (r.error or "transaction_failed").strip()[:260]
        url = (r.details or {}).get("final_url")
        lines.append(f"- {r.domain} [{r.name}]: {err} ({ms}) url={url}")
    return "\n".join(lines).strip()


def build_synthetic_dispatch_prompt(*, failures: list[SyntheticTransactionResult]) -> str:
    """Return the existing bounded message without invoking a transport."""
    payload = [
        {
            "domain": r.domain,
            "name": r.name,
            "elapsed_ms": r.elapsed_ms,
            "error": r.error,
            "details": r.details,
            "browser_infra_error": r.browser_infra_error,
        }
        for r in failures[:25]
    ]
    details = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "The service-monitoring detected synthetic end-to-end transaction failures (Playwright step flows).\n\n"
        "Failures (JSON):\n"
        f"{details}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Reproduce the failing transaction(s) from the production host (Playwright or curl where possible).\n"
        "2) Determine whether the failure is frontend regression, backend/API failure, "
        "reverse proxy issue, or auth flow change.\n"
        "3) Inspect relevant containers and logs.\n"
        "4) Provide a remediation plan for a human operator (no changes executed).\n\n"
        "Return a concise final report with:\n"
        "- Root cause + evidence\n"
        "- Impacted domains/transactions\n"
        "- Recommended safe remediation steps\n"
    )


def build_web_vitals_alert_message(
    *,
    failures: list[WebVitalsResult],
    thresholds: dict[str, float | None],
    down_after_failures: int,
    fail_streak: int,
) -> str:
    """Return the existing bounded message without invoking a transport."""
    lines = ["Monitor warning: Core Web Vitals are degraded ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    th = ", ".join(f"{k}={v}" for k, v in thresholds.items() if v is not None)
    if th:
        lines.append(f"Thresholds: {th}")
    lines.append("")
    for r in failures[:15]:
        # Browser evaluation returns JSON-valued metric fields.
        m = cast("JsonObject", r.metrics or {})
        lcp = m.get("lcp_ms")
        cls = m.get("cls")
        inp = m.get("inp_ms")
        err = (r.error or "").strip()[:260]
        parts: list[str] = []
        if lcp is not None:
            parts.append(f"LCP={round(required_float(lcp))}ms")
        if cls is not None:
            parts.append(f"CLS={required_float(cls):.3f}")
        if inp is not None:
            parts.append(f"INP~={round(required_float(inp))}ms")
        vit = " ".join(parts) if parts else "metrics=n/a"
        extra = f" error={err}" if err else ""
        lines.append(f"- {r.domain}: {vit}{extra}")
    return "\n".join(lines).strip()


def build_web_vitals_dispatch_prompt(*, failures: list[WebVitalsResult]) -> str:
    """Return the existing bounded message without invoking a transport."""
    payload = [
        {
            "domain": r.domain,
            "metrics": r.metrics,
            "error": r.error,
            "elapsed_ms": r.elapsed_ms,
            "browser_infra_error": r.browser_infra_error,
        }
        for r in failures[:25]
    ]
    details = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "The service-monitoring detected degraded Core Web Vitals (LCP/CLS/INP approximation).\n\n"
        "Failures (JSON):\n"
        f"{details}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Confirm the vitals with Lighthouse / Chrome DevTools (from the production host) for affected domains.\n"
        "2) Identify likely causes (slow backend/TTFB, oversized assets, render-blocking JS/CSS, layout shifts).\n"
        "3) Provide a remediation plan for a human operator (no changes executed).\n\n"
        "Return a concise final report with:\n"
        "- Most likely cause + evidence\n"
        "- Impacted domains\n"
        "- Recommended safe remediation steps\n"
    )
