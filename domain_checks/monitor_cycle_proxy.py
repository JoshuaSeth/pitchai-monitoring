# Copyright (c) 2026 PitchAI. All rights reserved.
"""Reverse-proxy header, access-log, and upstream-error monitor cycle."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from domain_checks.monitor_alerts import signal_alert
from domain_checks.monitor_context import Investigation
from domain_checks.monitor_proxy_observations import (
    access_percent,
    collect_access_observation,
    collect_header_issues,
    collect_upstream_observation,
    upstream_violation,
)
from domain_checks.monitor_values import int_value

if TYPE_CHECKING:
    from domain_checks.metrics_nginx import (
        NginxAccessWindowStats,
        NginxUpstreamErrorEvent,
        NginxUpstreamSummary,
    )
    from domain_checks.metrics_proxy import ProxyIssue
    from domain_checks.monitor_context import DomainCycle, MonitorContext
    from domain_checks.types import JsonObject, JsonValue


def _issue_evidence(issues: list[ProxyIssue]) -> list[JsonObject]:
    return [
        {
            "domain": issue.domain,
            "reason": issue.reason,
            "header": issue.header,
            "value": issue.value,
            "details": issue.details,
        }
        for issue in issues
    ]


def _proxy_details(
    issues: list[ProxyIssue],
    stats: NginxAccessWindowStats | None,
    summary: NginxUpstreamSummary | None,
) -> list[str]:
    details = [f"{issue.domain}: {issue.reason} value={issue.value}" for issue in issues]
    percentage = access_percent(stats)
    if stats is not None:
        details.append(
            f"access log: 502/504={percentage or 0.0:.2f}% "
            f"({stats.status_502_504}/{stats.total})",
        )
    if summary is not None:
        for server, count in sorted(summary["counts_by_server"].items()):
            details.append(f"upstream errors: server={server} count={count}")
    return details


def _evidence(
    issues: list[ProxyIssue],
    stats: NginxAccessWindowStats | None,
    events: list[NginxUpstreamErrorEvent],
    window_seconds: int,
) -> JsonObject:
    return {
        "window_seconds": window_seconds,
        "upstream_header_issues": _issue_evidence(issues),
        "access": (
            {
                "total": stats.total,
                "status_502_504": stats.status_502_504,
                "percent_502_504": access_percent(stats),
                "samples": stats.sample_lines,
            }
            if stats is not None
            else None
        ),
        "upstream_errors": [
            {
                "timestamp": event.ts,
                "server": event.server,
                "upstream": event.upstream,
                "message": event.message,
            }
            for event in events[:50]
        ],
    }


async def run_proxy_cycle(ctx: MonitorContext, cycle: DomainCycle) -> None:
    """Evaluate proxy signals and emit edge-triggered notices."""
    policy = ctx.settings.feature("proxy")
    if not policy.enabled or not cycle.results:
        return
    options = policy.options
    issues = collect_header_issues(ctx, cycle)
    window = max(60, int_value(options.get("window_seconds"), default=300))
    access_stats, access_percentage, access_violation = collect_access_observation(
        options,
        window,
    )
    upstream_events, summary = collect_upstream_observation(ctx, options, window)
    upstream_degraded = upstream_violation(ctx, cycle, summary, options)
    observed_ok = not issues and not access_violation and not upstream_degraded
    transition = ctx.observe_global("proxy", observed_ok=observed_ok, policy=policy)
    ctx.append_signal(
        "proxy",
        [
            cycle.started_ts,
            int(transition.effective_ok),
            len(issues),
            access_percentage,
            access_stats.total if access_stats is not None else 0,
            access_stats.status_502_504 if access_stats is not None else 0,
            len(upstream_events),
        ],
    )
    if transition.degraded:
        evidence = _evidence(issues, access_stats, upstream_events, window)
        ctx.events.append(
            "proxy_degraded",
            occurred_at=cycle.started_ts,
            upstream_issues=len(issues),
            access_502_504_percent=access_percentage,
            upstream_events=len(upstream_events),
        )
        await ctx.alert(
            signal_alert(
                "Monitor warning: proxy/upstream signals are degraded ⚠️",
                _proxy_details(issues, access_stats, summary),
                fail_streak=transition.fail_streak,
                down_after_failures=policy.down_after_failures,
            ),
        )
        if policy.dispatch_on_degraded:
            ctx.dispatch(
                Investigation(
                    state_key="service-monitoring.proxy",
                    title="Proxy/upstream investigation",
                    subject="reverse-proxy or upstream signals are degraded",
                    scope="Inspect upstream headers and bounded Nginx log evidence.",
                ),
                evidence=cast("JsonValue", evidence),
            )
    if transition.recovered:
        ctx.events.append("proxy_recovered", occurred_at=cycle.started_ts)
        if policy.notify_on_recovery:
            await ctx.recovery("Proxy/upstream signals recovered ✅")
