# Copyright (c) 2026 PitchAI. All rights reserved.
"""Scheduled Docker container-health monitor cycle."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, cast

from domain_checks.metrics_container_health import check_container_health
from domain_checks.monitor_alerts import signal_alert
from domain_checks.monitor_context import Investigation
from domain_checks.monitor_values import json_float, string_list

if TYPE_CHECKING:
    from domain_checks.container_models import ContainerHealthIssue
    from domain_checks.monitor_context import DomainCycle, MonitorContext
    from domain_checks.types import JsonObject, JsonValue


def _issue_evidence(issues: list[ContainerHealthIssue]) -> list[JsonObject]:
    return [
        {
            "name": issue.name,
            "container_id": issue.container_id,
            "running": issue.running,
            "status": issue.status,
            "restart_count": issue.restart_count,
            "restart_increase": issue.restart_increase,
            "oom_killed": issue.oom_killed,
            "health_status": issue.health_status,
            "exit_code": issue.exit_code,
            "error": issue.error,
        }
        for issue in issues
    ]


def _issue_details(issues: list[ContainerHealthIssue]) -> list[str]:
    details: list[str] = []
    for issue in issues:
        signals = [
            f"running={issue.running}",
            f"health={issue.health_status}",
            f"exit={issue.exit_code}",
            f"restart_delta={issue.restart_increase}",
        ]
        if issue.error:
            signals.append(f"error={issue.error}")
        details.append(f"{issue.name}: {' '.join(signals)}")
    return details


async def run_container_cycle(ctx: MonitorContext, cycle: DomainCycle) -> None:
    """Run a due Docker health scan and emit edge-triggered notices."""
    policy = ctx.settings.feature("container_health")
    status = ctx.state.global_signals["container_health"]
    now = time.time()
    if not policy.enabled or now - status.last_run_ts < policy.interval_seconds:
        return
    status.last_run_ts = now
    options = policy.options
    issues, restart_counts = await check_container_health(
        docker_socket_path=str(options.get("docker_socket_path") or "/var/run/docker.sock"),
        include_name_patterns=string_list(
            options.get("include_name_patterns"),
            description="container_health.include_name_patterns",
        ),
        exclude_name_patterns=string_list(
            options.get("exclude_name_patterns"),
            description="container_health.exclude_name_patterns",
        ),
        monitor_all=bool(options.get("monitor_all", False)),
        previous_restart_counts=ctx.state.collections.restart_counts,
        timeout_seconds=json_float(options.get("timeout_seconds", 3.0)),
    )
    ctx.state.collections.restart_counts = restart_counts
    transition = ctx.observe_global("container_health", observed_ok=not issues, policy=policy)
    ctx.append_signal(
        "container_health",
        [cycle.started_ts, int(transition.effective_ok), len(issues)],
    )
    if transition.degraded and issues:
        evidence = _issue_evidence(issues)
        ctx.events.append(
            "container_health_degraded",
            occurred_at=cycle.started_ts,
            issues=[issue.name for issue in issues[:20]],
        )
        await ctx.alert(
            signal_alert(
                "Monitor warning: Docker container health is degraded ⚠️",
                _issue_details(issues),
                fail_streak=transition.fail_streak,
                down_after_failures=policy.down_after_failures,
            ),
        )
        if policy.dispatch_on_degraded:
            ctx.dispatch(
                Investigation(
                    state_key="service-monitoring.container-health",
                    title="Container health investigation",
                    subject="Docker container health signals are degraded",
                    scope="Inspect container state, health checks, exit codes, OOM flags, and restart changes.",
                ),
                evidence=cast("JsonValue", evidence),
            )
    if transition.recovered:
        ctx.events.append("container_health_recovered", occurred_at=cycle.started_ts)
        if policy.notify_on_recovery:
            await ctx.recovery("Container health recovered ✅")
