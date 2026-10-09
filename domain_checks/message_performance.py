# Copyright (c) 2026 PitchAI. All rights reserved.
"""Pure performance warning and diagnostic text with existing limits."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, cast

from .cycle_values import coerce_optional_float
from .message_templates import dispatch_read_only_rules as _dispatch_read_only_rules

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .event_bus_delivery import JsonObject, JsonValue


def format_ms(value: JsonValue) -> str:
    """Format finite scalar milliseconds with the existing round-to-even rule.

    Returns:
        The formatted value, or the existing unavailable label.
    """
    number = coerce_optional_float(value)
    if number is None or not math.isfinite(number):
        return "n/a"
    return f"{round(number)}ms"


def build_performance_alert_message(
    *,
    slow: list[JsonObject],
    down_after_failures: int,
    fail_streak: int,
) -> str:
    """Return the existing bounded warning without choosing a recipient."""
    lines = ["Monitor warning: website performance is degraded ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.extend(("", "Slow domains (HTTP / Browser):"))
    for entry in slow[:12]:
        domain = entry.get("domain")
        http_ms = format_ms(entry.get("http_ms"))
        browser_ms = format_ms(entry.get("browser_ms"))
        reasons = cast("Sequence[JsonValue]", entry.get("reasons") or [])
        reason_parts = (str(x) for x in reasons[:3])
        reason_txt = ",".join(reason_parts) if reasons else "slow"
        lines.append(f"- {domain}: {http_ms} / {browser_ms} ({reason_txt})")
    return "\n".join(lines).strip()


def build_performance_dispatch_prompt(*, slow: list[JsonObject]) -> str:
    """Return the existing bounded diagnostic request without dispatching."""
    entries = slow[:20]
    slow_lines: list[str] = []
    for e in entries:
        domain = e.get("domain")
        http_ms = format_ms(e.get("http_ms"))
        browser_ms = format_ms(e.get("browser_ms"))
        reasons = cast("Sequence[JsonValue]", e.get("reasons") or [])
        reason_parts = (str(x) for x in reasons[:4])
        reason_txt = ", ".join(reason_parts) if reasons else "slow"
        slow_lines.append(f"- {domain}: HTTP {http_ms}, Browser {browser_ms} ({reason_txt})")
    slow_txt = "\n".join(slow_lines) if slow_lines else "(none)"
    return (
        "The production service-monitoring container detected consistently slow response times "
        "for monitored domains.\n\n"
        "Slow domains:\n"
        f"{slow_txt}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Reproduce timings from the production host with curl (include DNS/TLS/connect/TTFB/total breakdown).\n"
        "2) Check whether slowness is isolated to one domain or systemic (DNS, outbound network, CPU pressure).\n"
        "3) If the slow domain is reverse-proxied on the host, inspect the relevant proxy/container logs and health.\n"
        "4) Provide a clear triage summary and recommended next actions for a human operator.\n\n"
        "Return a concise final report with:\n"
        "- Reproduction results (commands + timings)\n"
        "- Most likely root cause + evidence\n"
        "- Impacted domains and whether it's systemic\n"
        "- Recommended safe remediation steps (no changes executed)\n"
    )
