# Copyright (c) 2026 PitchAI. All rights reserved.
"""Pure existing monitor text construction; no delivery or observation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .common_check import DomainCheckResult
    from .event_bus_delivery import JsonObject


def build_dispatch_prompt(result: DomainCheckResult) -> str:
    """Return the existing bounded message without invoking a transport."""
    details = json.dumps(result.details, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "A monitored domain is DOWN or showing a broken/maintenance page.\n\n"
        f"Domain: {result.domain}\n"
        f"Monitor reason: {result.reason}\n"
        "Monitor details (JSON):\n"
        f"{details}\n\n"
        f"{dispatch_read_only_rules()}\n"
        "Task:\n"
        f"1) Investigate why {result.domain} is not functioning properly on the production host.\n"
        "2) Use Docker to identify the relevant service container(s) and reverse proxy (by name/image/labels/ports).\n"
        "3) Inspect container status, recent restarts, health checks, and logs.\n"
        "4) Check for common root causes: upstream crash-loop, bad deploy, DNS, cert expiry, proxy config, "
        "resource exhaustion, and disk space issues.\n"
        "5) If you believe a restart or configuration change would help, "
        "suggest it as a human action but do not execute it.\n\n"
        "Return a concise final report with:\n"
        "- Root cause + evidence\n"
        "- Commands run (read-only diagnostics)\n"
        "- Current status + what to monitor next\n"
    )


def dispatch_read_only_rules() -> str:
    """Return the existing bounded message without invoking a transport."""
    return (
        "IMPORTANT safety rules:\n"
        "- Do NOT restart/stop/recreate any containers or services.\n"
        "- Do NOT deploy, update images, run apt-get, or change configuration files.\n"
        "- Do NOT prune/remove volumes/images/containers.\n"
        "- Only run read-only diagnostics (docker ps/inspect/logs/stats, curl, df, free, uptime, etc.).\n"
        "- If you believe a restart would help, suggest it as a human action but do not execute it.\n"
    )


def build_host_health_dispatch_prompt(*, violations: list[str], snap: JsonObject) -> str:
    """Return the existing bounded message without invoking a transport."""
    snap_json = json.dumps(snap, indent=2, ensure_ascii=False, sort_keys=True)
    violation_lines = (f"- {value}" for value in violations[:20])
    violations_txt = "\n".join(violation_lines) if violations else "(none)"
    return (
        "The production service-monitoring detected host health threshold violations "
        "(e.g. high CPU/RAM/disk usage).\n\n"
        f"Observed violations:\n{violations_txt}\n\n"
        "Host snapshot (JSON):\n"
        f"{snap_json}\n\n"
        f"{dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Confirm whether disk/memory/swap/cpu/load is actually under pressure on the production host.\n"
        "2) Identify top resource consumers (especially Docker containers).\n"
        "3) Gather evidence: docker ps, docker stats --no-stream, docker inspect (limits), "
        "df -h, df -i, free -m, uptime.\n"
        "4) Explain the most likely root cause(s) and the safest remediation steps for a human operator.\n\n"
        "Return a concise final report with:\n"
        "- Root cause hypothesis + evidence\n"
        "- What is consuming resources (container names, sizes, cpu/mem)\n"
        "- Immediate safe actions (non-disruptive) + next steps\n"
    )


def build_meta_alert_message(
    *,
    reasons: list[str],
    down_after_failures: int,
    fail_streak: int,
) -> str:
    """Return the existing bounded message without invoking a transport."""
    lines = ["Monitor warning: monitoring pipeline is degraded ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.append("")
    lines.extend(f"- {reason}" for reason in reasons[:12])
    return "\n".join(lines).strip()


def build_meta_dispatch_prompt(*, reasons: list[str], context: JsonObject) -> str:
    """Return the existing bounded message without invoking a transport."""
    details = json.dumps({"reasons": reasons[:25], "context": context}, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "The service-monitoring detected that the monitoring pipeline itself is degraded "
        "(cycle overruns/state write failures/etc.).\n\n"
        "Details (JSON):\n"
        f"{details}\n\n"
        f"{dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Confirm whether the service-monitoring container is overloaded (CPU/mem), or stuck (slow cycles).\n"
        "2) Check host resource pressure and docker stats.\n"
        "3) Check monitor container logs for repeated errors (state write, Telegram, Playwright launch).\n"
        "4) Provide a safe remediation plan for a human operator (no changes executed).\n\n"
        "Return a concise final report with:\n"
        "- Root cause hypothesis + evidence\n"
        "- Impact (are we missing checks/alerts?)\n"
        "- Recommended safe remediation steps\n"
    )
