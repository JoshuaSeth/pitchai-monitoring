# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing API-contract warning and investigation text, with no delivery."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from .message_templates import dispatch_read_only_rules

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject
    from .metrics_api_contract import ApiContractCheckResult


def build_api_contract_alert_message(*, failures: list[ApiContractCheckResult],
                                     down_after_failures: int, fail_streak: int) -> str:
    """Return the existing bounded API warning without changing message content."""
    lines = ["Monitor warning: API contract checks are failing ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.append("")
    for result in failures[:15]:
        status = "n/a" if result.status_code is None else str(result.status_code)
        elapsed = "n/a" if result.elapsed_ms is None else f"{round(float(result.elapsed_ms))!s}ms"
        error = (result.error or "contract_failed").strip()[:260]
        lines.append(f"- {result.domain} [{result.name}]: {error} status={status} ({elapsed}) url={result.url}")
    return "\n".join(lines).strip()


def build_api_contract_dispatch_prompt(*, failures: list[ApiContractCheckResult]) -> str:
    """Return the same bounded diagnostic prompt and existing read-only scope."""
    selected = failures[:30]
    payload: list[JsonObject] = [
        {"domain": result.domain, "name": result.name, "url": result.url,
         "status_code": result.status_code, "elapsed_ms": result.elapsed_ms,
         "error": result.error, "details": cast("JsonObject", result.details)}
        for result in selected
    ]
    details = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "The service-monitoring detected API contract failures "
        "(JSON endpoints returning unexpected status/shape/latency).\n\n"
        "Failing checks (JSON):\n"
        f"{details}\n\n"
        f"{dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Reproduce the failing API calls from the production host (curl -i).\n"
        "2) Determine whether the issue is backend crash, reverse proxy routing, deploy regression, or auth/config.\n"
        "3) Identify the relevant container(s) and inspect logs/health/restarts.\n"
        "4) Provide a clear remediation plan for a human operator (no changes executed).\n\n"
        "Return a concise final report with:\n"
        "- Root cause + evidence\n"
        "- Impacted endpoints\n"
        "- Recommended safe remediation steps\n"
    )
