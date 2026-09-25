# Copyright (c) 2026 PitchAI. All rights reserved.
"""Host-health and per-domain performance monitor cycles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from domain_checks.monitor_alerts import performance_details, signal_alert
from domain_checks.monitor_context import Investigation
from domain_checks.monitor_host import collect_host_snapshot
from domain_checks.monitor_host_policy import collect_host_health_violations
from domain_checks.monitor_performance import collect_performance_violations
from domain_checks.monitor_values import (
    json_float,
    json_int,
    json_object,
    optional_float,
    string_list,
)

if TYPE_CHECKING:
    from domain_checks.monitor_context import DomainCycle, MonitorContext
    from domain_checks.types import JsonObject, JsonValue


@dataclass(frozen=True)
class HealthCycle:
    """Host and performance evidence rendered in the heartbeat."""

    host_snapshot: JsonObject | None
    host_violations: list[str] | None
    performance_slow: list[JsonObject] | None


def _record_host_snapshot(ctx: MonitorContext, snapshot: JsonObject) -> None:
    next_total = snapshot.get("cpu_prev_total_next")
    next_idle = snapshot.get("cpu_prev_idle_next")
    if next_total is not None and next_idle is not None:
        ctx.state.metadata.host_cpu_prev_total = json_int(next_total)
        ctx.state.metadata.host_cpu_prev_idle = json_int(next_idle)
    persisted = dict(snapshot)
    persisted.pop("cpu_prev_total_next", None)
    persisted.pop("cpu_prev_idle_next", None)
    ctx.state.metadata.host_last_snapshot = persisted


def _worst_disk(snapshot: JsonObject) -> float | None:
    worst: float | None = None
    for info in json_object(snapshot.get("disk")).values():
        used = optional_float(json_object(info).get("used_percent"))
        if used is not None and (worst is None or used > worst):
            worst = used
    return worst


async def _host_cycle(
    ctx: MonitorContext, cycle: DomainCycle,
) -> tuple[JsonObject, list[str]] | None:
    policy = ctx.settings.feature("host_health")
    if not policy.enabled:
        return None
    options = policy.options
    disk_paths = string_list(
        options.get("disk_paths"), description="host_health.disk_paths",
    ) or ["/"]
    snapshot = collect_host_snapshot(
        disk_paths=disk_paths,
        cpu_prev_total=ctx.state.metadata.host_cpu_prev_total,
        cpu_prev_idle=ctx.state.metadata.host_cpu_prev_idle,
    )
    violations = collect_host_health_violations(
        snapshot,
        disk_used_percent_max=optional_float(options.get("disk_used_percent_max")),
        mem_used_percent_max=optional_float(options.get("mem_used_percent_max")),
        swap_used_percent_max=optional_float(options.get("swap_used_percent_max")),
        cpu_used_percent_max=optional_float(options.get("cpu_used_percent_max")),
        load1_per_cpu_max=optional_float(options.get("load1_per_cpu_max")),
    )
    _record_host_snapshot(ctx, snapshot)
    transition = ctx.observe_global(
        "host_health", observed_ok=not violations, policy=policy,
    )
    ctx.append_signal(
        "host_health",
        [
            cycle.started_ts,
            int(transition.effective_ok),
            snapshot.get("mem_used_percent"),
            snapshot.get("swap_used_percent"),
            snapshot.get("cpu_used_percent"),
            snapshot.get("load1_per_cpu"),
            _worst_disk(snapshot),
            len(violations),
        ],
    )
    if transition.degraded and violations:
        ctx.events.append(
            "host_health_degraded",
            occurred_at=cycle.started_ts,
            violations=violations[:20],
        )
        await ctx.alert(
            signal_alert(
                "Monitor warning: host health thresholds exceeded ⚠️",
                violations,
                fail_streak=transition.fail_streak,
                down_after_failures=policy.down_after_failures,
            ),
        )
        if policy.dispatch_on_degraded:
            ctx.dispatch(
                Investigation(
                    state_key="service-monitoring.host-health",
                    title="Host health investigation",
                    subject="host health thresholds are exceeded",
                    scope="Inspect memory, swap, disk, CPU, and load without mutating services or infrastructure.",
                ),
                evidence={"snapshot": snapshot, "violations": violations},
            )
    if transition.recovered:
        ctx.events.append("host_health_recovered", occurred_at=cycle.started_ts)
        if policy.notify_on_recovery:
            await ctx.recovery(
                "Host health recovered ✅ (threshold violations cleared).",
            )
    return snapshot, violations


async def _performance_cycle(
    ctx: MonitorContext, cycle: DomainCycle,
) -> list[JsonObject] | None:
    policy = ctx.settings.feature("performance")
    if not policy.enabled or not cycle.results:
        return None
    options = policy.options
    overrides = json_object(options.get("per_domain_overrides"))
    violations = collect_performance_violations(
        cycle.results,
        http_elapsed_ms_max=json_float(options.get("http_elapsed_ms_max", 1500.0)),
        browser_elapsed_ms_max=json_float(
            options.get("browser_elapsed_ms_max", 4000.0),
        ),
        per_domain_overrides=overrides,
    )
    alertable = ctx.alertable_domains
    routed = [item for item in violations if str(item.get("domain")) in alertable]
    transition = ctx.observe_global(
        "performance", observed_ok=not routed, policy=policy,
    )
    ctx.append_signal(
        "performance", [cycle.started_ts, int(transition.effective_ok), len(routed)],
    )
    if transition.degraded and routed:
        ctx.events.append(
            "performance_degraded",
            occurred_at=cycle.started_ts,
            slow_domains=[item.get("domain") for item in routed[:20]],
        )
        await ctx.alert(
            signal_alert(
                "Monitor warning: website performance is degraded ⚠️",
                performance_details(routed),
                fail_streak=transition.fail_streak,
                down_after_failures=policy.down_after_failures,
            ),
        )
        if policy.dispatch_on_degraded:
            ctx.dispatch(
                Investigation(
                    state_key="service-monitoring.performance",
                    title="Performance investigation",
                    subject="website response times exceed configured thresholds",
                    scope=(
                        "Inspect application, reverse-proxy, network, and browser timing evidence for affected "
                        "domains."
                    ),
                ),
                evidence=cast("JsonValue", routed),
            )
    if transition.recovered:
        ctx.events.append("performance_recovered", occurred_at=cycle.started_ts)
        if policy.notify_on_recovery:
            await ctx.recovery(
                "Performance recovered ✅ (response times back under thresholds).",
            )
    return routed


async def run_health_cycles(ctx: MonitorContext, cycle: DomainCycle) -> HealthCycle:
    """Run host and per-domain performance policies.

    Returns:
        Evidence needed by the scheduled heartbeat.
    """
    host = await _host_cycle(ctx, cycle)
    performance = await _performance_cycle(ctx, cycle)
    snapshot, violations = host if host is not None else (None, None)
    return HealthCycle(
        host_snapshot=snapshot, host_violations=violations, performance_slow=performance,
    )
