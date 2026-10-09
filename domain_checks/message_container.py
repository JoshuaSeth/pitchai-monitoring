# Copyright (c) 2026 PitchAI. All rights reserved.
"""Pure existing monitor text construction; no delivery or observation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .message_templates import dispatch_read_only_rules as _dispatch_read_only_rules

if TYPE_CHECKING:
    from .metrics_container_health import ContainerHealthIssue


def build_container_health_alert_message(
    *,
    issues: list[ContainerHealthIssue],
    down_after_failures: int,
    fail_streak: int,
) -> str:
    """Return the existing bounded message without invoking a transport."""
    lines = ["Monitor warning: Docker container health is degraded ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.append("")
    for it in issues[:15]:
        parts: list[str] = []
        if it.running is False:
            parts.append("NOT_RUNNING")
        if it.health_status and it.health_status != "healthy":
            parts.append(f"health={it.health_status}")
        if it.oom_killed:
            parts.append("OOMKilled")
        if it.restart_increase is not None and it.restart_increase > 0:
            parts.append(f"restarted(+{it.restart_increase})")
        if it.exit_code is not None and it.exit_code != 0:
            parts.append(f"exit={it.exit_code}")
        if it.error:
            parts.append(f"error={it.error}")
        flags = ",".join(parts) if parts else "issue"
        lines.append(f"- {it.name} ({it.container_id}): {flags} status={it.status}")
    return "\n".join(lines).strip()


def build_container_health_dispatch_prompt(*, issues: list[ContainerHealthIssue]) -> str:
    """Return the existing bounded message without invoking a transport."""
    payload = [
        {
            "name": it.name,
            "container_id": it.container_id,
            "running": it.running,
            "status": it.status,
            "restart_count": it.restart_count,
            "restart_increase": it.restart_increase,
            "oom_killed": it.oom_killed,
            "health_status": it.health_status,
            "exit_code": it.exit_code,
            "error": it.error,
        }
        for it in issues[:25]
    ]
    details = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "The service-monitoring detected Docker container health issues (unhealthy/not running/restarting/OOM).\n\n"
        "Issues (JSON):\n"
        f"{details}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Confirm container states with docker ps/inspect, and check recent restarts/OOMKilled.\n"
        "2) Gather logs for the affected containers (docker logs --tail 200).\n"
        "3) Correlate with host resource pressure (df/free/uptime) and recent deploys.\n"
        "4) Provide a remediation plan for a human operator (no changes executed).\n\n"
        "Return a concise final report with:\n"
        "- Root cause + evidence\n"
        "- Affected containers + status\n"
        "- Recommended safe remediation steps\n"
    )
