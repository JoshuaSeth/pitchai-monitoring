# Copyright (c) 2026 PitchAI. All rights reserved.
"""Pure existing monitor text construction; no delivery or observation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .message_templates import dispatch_read_only_rules as _dispatch_read_only_rules

if TYPE_CHECKING:
    from .metrics_red import RedViolation
    from .metrics_slo import SloBurnViolation


def build_slo_alert_message(
    *,
    violations: list[SloBurnViolation],
    slo_target_percent: float,
    down_after_failures: int,
    fail_streak: int,
) -> str:
    """Return the existing bounded message without invoking a transport."""
    lines = ["Monitor warning: SLO error budget burn rate is high ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.extend((f"SLO target: {float(slo_target_percent):.3f}%", ""))
    for v in violations[:15]:
        s_av = "n/a" if v.short_availability_percent is None else f"{v.short_availability_percent:.3f}%"
        l_av = "n/a" if v.long_availability_percent is None else f"{v.long_availability_percent:.3f}%"
        lines.append(
            f"- {v.domain}: rule={v.rule} burn={v.short_burn_rate:.2f}/{v.long_burn_rate:.2f} "
            f"avail={s_av}/{l_av} samples={v.short_total}/{v.long_total} "
            f"windows={v.short_window_minutes}m/{v.long_window_minutes}m",
        )
    return "\n".join(lines).strip()


def build_slo_dispatch_prompt(*, violations: list[SloBurnViolation], slo_target_percent: float) -> str:
    """Return the existing bounded message without invoking a transport."""
    payload = [
        {
            "domain": v.domain,
            "rule": v.rule,
            "short_window_minutes": v.short_window_minutes,
            "long_window_minutes": v.long_window_minutes,
            "short_burn_rate": v.short_burn_rate,
            "long_burn_rate": v.long_burn_rate,
            "short_availability_percent": v.short_availability_percent,
            "long_availability_percent": v.long_availability_percent,
            "short_total": v.short_total,
            "long_total": v.long_total,
        }
        for v in violations[:30]
    ]
    details = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "The service-monitoring detected high error-budget burn rate (SLO at risk).\n\n"
        f"SLO target: {float(slo_target_percent):.3f}%\n\n"
        "Triggered burn-rate violations (JSON):\n"
        f"{details}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Identify which domains/services are causing burn-rate violations and whether issues are ongoing.\n"
        "2) Correlate with recent deploys, container restarts/OOMs, "
        "Nginx upstream errors, and host resource pressure.\n"
        "3) Provide a clear summary of likely root cause(s) and recommended next steps for a human operator.\n\n"
        "Return a concise final report with:\n"
        "- What is burning budget + since when\n"
        "- Root cause hypothesis + evidence\n"
        "- Recommended safe remediation steps\n"
    )


def build_red_alert_message(
    *,
    violations: list[RedViolation],
    window_minutes: int,
    down_after_failures: int,
    fail_streak: int,
) -> str:
    """Return the existing bounded message without invoking a transport."""
    lines = ["Monitor warning: RED / golden-signal checks are degraded ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.extend((f"Window: {int(window_minutes)}m", ""))
    for v in violations[:15]:
        err = "n/a" if v.error_rate_percent is None else f"{v.error_rate_percent:.2f}%"
        http_p95 = "n/a" if v.http_p95_ms is None else f"{round(v.http_p95_ms)}ms"
        br_p95 = "n/a" if v.browser_p95_ms is None else f"{round(v.browser_p95_ms)}ms"
        reasons = ",".join(v.reasons[:4]) if v.reasons else "degraded"
        lines.append(
            f"- {v.domain}: {reasons} err={err} http_p95={http_p95} browser_p95={br_p95} samples={v.total_samples}",
        )
    return "\n".join(lines).strip()


def build_red_dispatch_prompt(*, violations: list[RedViolation], window_minutes: int) -> str:
    """Return the existing bounded message without invoking a transport."""
    payload = [
        {
            "domain": v.domain,
            "reasons": v.reasons,
            "total_samples": v.total_samples,
            "error_rate_percent": v.error_rate_percent,
            "http_p95_ms": v.http_p95_ms,
            "browser_p95_ms": v.browser_p95_ms,
        }
        for v in violations[:30]
    ]
    details = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "The service-monitoring detected degraded RED/golden signals (error-rate and/or latency percentiles).\n\n"
        f"Window: {int(window_minutes)} minutes\n\n"
        "Violations (JSON):\n"
        f"{details}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Reproduce latency and errors from the production host (curl timings; check DNS/TLS/connect/TTFB/total).\n"
        "2) Determine whether the issue is isolated to one service or systemic (host load, network, DNS).\n"
        "3) Check container status/restarts and relevant logs for the impacted services.\n"
        "4) Provide a triage summary and recommended next steps for a human operator.\n\n"
        "Return a concise final report with:\n"
        "- Reproduction results\n"
        "- Root cause hypothesis + evidence\n"
        "- Recommended safe remediation steps\n"
    )
