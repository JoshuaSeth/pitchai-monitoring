# Copyright (c) 2026 PitchAI. All rights reserved.
"""Operator-facing monitor alerts and dispatcher evidence prompts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from domain_checks.monitor_values import json_array, json_float

if TYPE_CHECKING:
    from domain_checks.common_check import DomainCheckResult
    from domain_checks.types import JsonObject, JsonValue


def format_ms(value: JsonValue) -> str:
    """Format an optional latency value.

    Returns:
        A rounded millisecond label or ``n/a``.
    """
    if value is None:
        return "n/a"
    try:
        return f"{round(json_float(value))}ms"
    except (TypeError, ValueError):
        return "n/a"


def domain_down_alert(result: DomainCheckResult) -> str:
    """Build the detailed debounced domain-down alert.

    Returns:
        The operator-facing alert text.
    """
    details = result.details
    lines = [f"{result.domain} is DOWN ❌", f"Reason: {result.reason}"]
    failures = details.get("fail_streak")
    threshold = details.get("down_after_failures")
    if isinstance(failures, int) and isinstance(threshold, int) and threshold > 1:
        lines.append(f"Debounce: fail_streak={failures}/{threshold}")
    if details.get("status_code") is not None:
        lines.append(f"HTTP: {details['status_code']} ({format_ms(details.get('http_elapsed_ms'))})")
    if details.get("http_status") is not None:
        lines.append(f"Browser: {details['http_status']} ({format_ms(details.get('browser_elapsed_ms'))})")
    final_url = details.get("final_url")
    if isinstance(final_url, str) and final_url.strip():
        lines.append(f"Final URL: {final_url.strip()[:1000]}")
    if details.get("final_host_ok") is False:
        lines.append(
            f"Final host mismatch: got={details.get('final_host')} "
            f"expected_suffix={details.get('expected_final_host_suffix')}",
        )
    if details.get("title_ok") is False:
        lines.append(f"Title mismatch: {details.get('title')!r}")
    error = details.get("error")
    if isinstance(error, str) and error.strip():
        lines.append(f"Error: {error.strip()[:500]}")
    detail_lists = (
        ("Forbidden text hit", details.get("forbidden_hits"), 8),
        ("Missing selectors", details.get("missing_selectors_all"), 5),
        ("Missing text", details.get("missing_text"), 5),
    )
    for label, value, limit in detail_lists:
        if isinstance(value, list) and value:
            items = [str(item) for item in value[:limit]]
            lines.append(f"{label}: {', '.join(items)}")
    return "\n".join(lines).strip()


def signal_alert(
    title: str,
    details: list[str],
    *,
    fail_streak: int,
    down_after_failures: int,
) -> str:
    """Build a consistent debounced feature-degradation alert.

    Returns:
        The operator-facing alert text.
    """
    lines = [title]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.append("")
    lines.extend(f"- {detail}" for detail in details[:20])
    return "\n".join(lines).strip()


def performance_details(slow: list[JsonObject]) -> list[str]:
    """Format performance violations for an alert.

    Returns:
        Concise details for the bounded performance violations.
    """
    details: list[str] = []
    for item in slow[:12]:
        reasons = ",".join(str(value) for value in json_array(item.get("reasons"))[:3]) or "slow"
        details.append(
            f"{item.get('domain')}: {format_ms(item.get('http_ms'))} / {format_ms(item.get('browser_ms'))} ({reasons})",
        )
    return details


def dispatch_prompt(subject: str, evidence: JsonValue, *, remediation_scope: str) -> str:
    """Build a read-only evidence-first dispatcher investigation prompt.

    Returns:
        The evidence-first investigation prompt.
    """
    serialized = json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        f"You are investigating PitchAI service monitoring: {subject}.\n\n"
        f"Evidence:\n{serialized}\n\n"
        "Use read-only diagnostics first. Do not restart services, edit files, deploy, or change infrastructure.\n"
        "Do not expose credentials, tokens, cookies, or authorization headers.\n"
        f"Scope: {remediation_scope}\n\n"
        "Report: root-cause hypothesis with evidence, user impact, and safe remediation steps."
    )


def domain_dispatch_prompt(result: DomainCheckResult) -> str:
    """Build the domain-specific dispatcher prompt.

    Returns:
        The domain investigation prompt.
    """
    return dispatch_prompt(
        f"domain {result.domain} is down ({result.reason})",
        cast("JsonValue", result.details),
        remediation_scope=(
            f"Inspect DNS, TLS, HTTP, browser assertions, reverse proxy, and containers for {result.domain}."
        ),
    )


def objects_as_details(items: list[JsonObject], *, name_key: str = "domain") -> list[str]:
    """Format bounded structured failures without losing their evidence.

    Returns:
        One concise line per structured failure.
    """
    details: list[str] = []
    for item in items[:20]:
        serialized = json.dumps(item, ensure_ascii=False, sort_keys=True)
        details.append(f"{item.get(name_key, 'item')}: {serialized}")
    return details
