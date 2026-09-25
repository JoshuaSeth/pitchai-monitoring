# Copyright (c) 2026 PitchAI. All rights reserved.
"""Monitoring-pipeline health and persistence-failure cycle."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain_checks.monitor_alerts import signal_alert
from domain_checks.monitor_context import Investigation
from domain_checks.monitor_values import float_value, int_value

if TYPE_CHECKING:
    from domain_checks.monitor_context import DomainCycle, MonitorContext


async def run_meta_cycle(
    ctx: MonitorContext,
    cycle: DomainCycle,
    *,
    elapsed_seconds: float,
    browser_connected: bool,
) -> None:
    """Evaluate monitor-cycle overrun and state-persistence health."""
    policy = ctx.settings.feature("meta_monitoring")
    if not policy.enabled:
        return
    options = policy.options
    overrun_factor = float_value(options.get("cycle_overrun_factor"), default=1.25)
    overrun_threshold = ctx.settings.core.interval_seconds * overrun_factor
    write_failure_max = max(1, int_value(options.get("state_write_failures_max"), default=3))
    write_failures = ctx.state.metadata.state_write_fail_streak
    reasons: list[str] = []
    if elapsed_seconds > overrun_threshold:
        reasons.append(
            f"cycle_overrun: elapsed={elapsed_seconds:.3f}s > threshold={overrun_threshold:.3f}s "
            f"interval={ctx.settings.core.interval_seconds}s",
        )
    if write_failures >= write_failure_max:
        reasons.append(f"state_write_failures: streak={write_failures} >= {write_failure_max}")
    transition = ctx.observe_global("meta", observed_ok=not reasons, policy=policy)
    ctx.append_signal(
        "meta",
        [
            cycle.started_ts,
            int(transition.effective_ok),
            len(reasons),
            round(elapsed_seconds, 3),
            write_failures,
        ],
    )
    if transition.degraded and reasons:
        ctx.events.append("meta_degraded", occurred_at=cycle.started_ts, reasons=reasons[:20])
        await ctx.alert(
            signal_alert(
                "Monitor warning: monitoring pipeline is degraded ⚠️",
                reasons,
                fail_streak=transition.fail_streak,
                down_after_failures=policy.down_after_failures,
            ),
        )
        if policy.dispatch_on_degraded:
            evidence = {
                "reasons": reasons,
                "interval_seconds": ctx.settings.core.interval_seconds,
                "elapsed_seconds": round(elapsed_seconds, 3),
                "state_write_fail_streak": write_failures,
                "browser_connected": browser_connected,
                "check_concurrency": ctx.settings.core.check_concurrency,
                "browser_concurrency": ctx.settings.core.browser_concurrency,
            }
            ctx.dispatch(
                Investigation(
                    state_key="service-monitoring.meta",
                    title="Monitoring pipeline investigation",
                    subject="the monitoring pipeline itself is degraded",
                    scope="Inspect cycle timing, persistence, event delivery, browser state, and resource contention.",
                ),
                evidence=evidence,
            )
    if transition.recovered:
        ctx.events.append("meta_recovered", occurred_at=cycle.started_ts)
        if policy.notify_on_recovery:
            await ctx.recovery("Monitoring pipeline recovered ✅")
