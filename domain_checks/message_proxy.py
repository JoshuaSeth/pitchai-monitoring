# Copyright (c) 2026 PitchAI. All rights reserved.
"""Pure existing monitor text construction; no delivery or observation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, TypedDict, Unpack

from .cycle_values import required_int
from .message_templates import dispatch_read_only_rules as _dispatch_read_only_rules

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject
    from .metrics_nginx import NginxAccessWindowStats, NginxUpstreamErrorEvent
    from .metrics_proxy import ProxyIssue


class ProxyAlertInput(TypedDict):
    """The exact existing keyword fields used to describe a proxy observation."""

    upstream_issues: list[ProxyIssue]
    access_stats: NginxAccessWindowStats | None
    upstream_errors_summary: JsonObject | None
    window_seconds: int
    down_after_failures: int
    fail_streak: int


def build_proxy_alert_message(**values: Unpack[ProxyAlertInput]) -> str:
    """Return the existing bounded message without invoking a transport."""
    upstream_issues = values["upstream_issues"]
    access_stats = values["access_stats"]
    upstream_errors_summary = values["upstream_errors_summary"]
    window_seconds = values["window_seconds"]
    down_after_failures, fail_streak = values["down_after_failures"], values["fail_streak"]
    lines = ["Monitor warning: Reverse proxy / upstream signals are degraded ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.extend((f"Window: {int(window_seconds)}s", ""))

    if upstream_issues:
        lines.append("Upstream header issues:")
        lines.extend(f"- {it.domain}: {it.reason} {it.header}={it.value}" for it in upstream_issues[:12])
        lines.append("")

    if access_stats is not None:
        total = int(access_stats.total)
        rate_502 = 0.0
        if total > 0:
            rate_502 = (int(access_stats.status_502_504) / float(total)) * 100.0
        lines.append(
            f"Nginx access: total={total} 5xx={access_stats.status_5xx} "
            f"502/504={access_stats.status_502_504} ({rate_502:.2f}%)",
        )
        if access_stats.sample_lines:
            lines.append("Sample 502/504 lines:")
            lines.extend(f"- {ln}" for ln in access_stats.sample_lines[:6])
        lines.append("")

    counts = upstream_errors_summary.get("counts_by_server") if upstream_errors_summary else None
    if isinstance(counts, dict):
        lines.append("Nginx upstream errors (error.log):")
        ordered_counts = sorted(counts.items(), key=lambda kv: required_int(kv[1]), reverse=True)
        lines.extend(f"- {server}: {required_int(count)}" for server, count in ordered_counts[:10])
        lines.append("")

    return "\n".join(lines).strip()


def build_proxy_dispatch_prompt(
    *,
    upstream_issues: list[ProxyIssue],
    access_stats: NginxAccessWindowStats | None,
    upstream_error_events: list[NginxUpstreamErrorEvent],
    window_seconds: int,
) -> str:
    """Return the existing bounded message without invoking a transport."""
    payload = {
        "window_seconds": int(window_seconds),
        "upstream_header_issues": [
            {
                "domain": it.domain,
                "reason": it.reason,
                "header": it.header,
                "value": it.value,
                "details": it.details,
            }
            for it in upstream_issues[:25]
        ],
        "nginx_access": (
            {
                "total": access_stats.total,
                "status_5xx": access_stats.status_5xx,
                "status_502_504": access_stats.status_502_504,
                "status_4xx": access_stats.status_4xx,
                "sample_lines": access_stats.sample_lines[:8],
            }
            if access_stats is not None
            else None
        ),
        "nginx_upstream_errors": [
            {"ts": e.ts, "level": e.level, "server": e.server, "upstream": e.upstream, "message": e.message}
            for e in upstream_error_events[:60]
        ],
    }
    details = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "The service-monitoring detected reverse proxy upstream/failover issues "
        "(backup upstream, 502/504 spike, or upstream errors).\n\n"
        "Details (JSON):\n"
        f"{details}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Confirm Nginx upstream status on the production host "
        "(curl -i to affected domains; inspect upstream headers).\n"
        "2) Check Nginx error.log for upstream failures and correlate to service containers/ports.\n"
        "3) Identify which upstream (primary/backup) is serving and why failover occurred.\n"
        "4) Provide a remediation plan for a human operator (no changes executed).\n\n"
        "Return a concise final report with:\n"
        "- Root cause + evidence\n"
        "- Impacted domains/upstreams\n"
        "- Recommended safe remediation steps\n"
    )
