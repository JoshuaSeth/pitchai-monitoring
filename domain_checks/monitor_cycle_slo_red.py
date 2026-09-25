# Copyright (c) 2026 PitchAI. All rights reserved.
"""History-driven SLO burn-rate and RED signal cycles."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, cast

from domain_checks.metrics_red import compute_red_violations
from domain_checks.metrics_slo import compute_slo_burn_violations
from domain_checks.monitor_alerts import signal_alert
from domain_checks.monitor_context import Investigation
from domain_checks.monitor_values import (
    int_value,
    json_array,
    json_float,
    optional_float,
)

if TYPE_CHECKING:
    from domain_checks.metrics_red import RedViolation
    from domain_checks.metrics_slo import SloBurnViolation
    from domain_checks.monitor_context import DomainCycle, MonitorContext
    from domain_checks.types import JsonObject, JsonValue

_DEFAULT_SLO_RULES: list[JsonValue] = [
    {
        "name": "page_fast_burn",
        "short_window_minutes": 5,
        "long_window_minutes": 60,
        "short_burn_rate": 14.4,
        "long_burn_rate": 6.0,
    },
    {
        "name": "ticket_slow_burn",
        "short_window_minutes": 360,
        "long_window_minutes": 4320,
        "short_burn_rate": 6.0,
        "long_burn_rate": 1.0,
    },
]


def _slo_evidence(violations: list[SloBurnViolation]) -> list[JsonObject]:
    return [
        {
            "domain": violation.domain,
            "rule": violation.rule,
            "short_burn_rate": violation.short_burn_rate,
            "long_burn_rate": violation.long_burn_rate,
            "short_availability_percent": violation.short_availability_percent,
            "long_availability_percent": violation.long_availability_percent,
            "short_total": violation.short_total,
            "long_total": violation.long_total,
        }
        for violation in violations
    ]


def _slo_details(violations: list[SloBurnViolation]) -> list[str]:
    return [
        (
            f"{violation.domain} [{violation.rule}] burn="
            f"{violation.short_burn_rate:.2f}/{violation.long_burn_rate:.2f}"
        )
        for violation in violations
    ]


async def run_slo_cycle(ctx: MonitorContext, cycle: DomainCycle) -> None:
    """Evaluate sustained SLO burn rates and emit edge-triggered notices."""
    policy = ctx.settings.feature("slo")
    if not policy.enabled or not ctx.state.history:
        return
    options = policy.options
    rules = json_array(options.get("burn_rate_rules")) or _DEFAULT_SLO_RULES
    violations = compute_slo_burn_violations(
        history_by_domain=ctx.state.history,
        now_ts=time.time(),
        slo_target_percent=json_float(options.get("target_percent", 99.9)),
        burn_rate_rules=rules,
        min_total_samples=max(
            1, int_value(options.get("min_total_samples"), default=5),
        ),
    )
    alertable = ctx.alertable_domains
    routed = [violation for violation in violations if violation.domain in alertable]
    transition = ctx.observe_global("slo", observed_ok=not routed, policy=policy)
    ctx.append_signal(
        "slo", [cycle.started_ts, int(transition.effective_ok), len(routed)],
    )
    if transition.degraded and routed:
        evidence = _slo_evidence(routed)
        ctx.events.append(
            "slo_degraded",
            occurred_at=cycle.started_ts,
            violations=len(routed),
            domains=[violation.domain for violation in routed[:20]],
        )
        await ctx.alert(
            signal_alert(
                "Monitor warning: SLO error-budget burn is elevated ⚠️",
                _slo_details(routed),
                fail_streak=transition.fail_streak,
                down_after_failures=policy.down_after_failures,
            ),
        )
        if policy.dispatch_on_degraded:
            ctx.dispatch(
                Investigation(
                    state_key="service-monitoring.slo",
                    title="SLO burn investigation",
                    subject="SLO error-budget burn is elevated",
                    scope="Inspect sustained availability failures and latency evidence for the affected domains.",
                ),
                evidence=cast("JsonValue", evidence),
            )
    if transition.recovered:
        ctx.events.append("slo_recovered", occurred_at=cycle.started_ts)
        if policy.notify_on_recovery:
            await ctx.recovery("SLO burn recovered ✅ (burn-rate violations cleared).")


def _red_evidence(violations: list[RedViolation]) -> list[JsonObject]:
    return [
        {
            "domain": violation.domain,
            "reasons": violation.reasons,
            "total_samples": violation.total_samples,
            "error_rate_percent": violation.error_rate_percent,
            "http_p95_ms": violation.http_p95_ms,
            "browser_p95_ms": violation.browser_p95_ms,
        }
        for violation in violations
    ]


def _red_details(violations: list[RedViolation]) -> list[str]:
    details: list[str] = []
    for violation in violations:
        reasons = ",".join(violation.reasons)
        details.append(
            f"{violation.domain}: {reasons} samples={violation.total_samples}",
        )
    return details


async def run_red_cycle(ctx: MonitorContext, cycle: DomainCycle) -> None:
    """Evaluate rolling RED signals and emit edge-triggered notices."""
    policy = ctx.settings.feature("red")
    if not policy.enabled or not ctx.state.history:
        return
    options = policy.options
    violations = compute_red_violations(
        history_by_domain=ctx.state.history,
        now_ts=time.time(),
        window_minutes=max(1, int_value(options.get("window_minutes"), default=30)),
        min_samples=max(1, int_value(options.get("min_samples"), default=10)),
        error_rate_max_percent=optional_float(options.get("error_rate_max_percent")),
        http_p95_ms_max=optional_float(options.get("http_p95_ms_max")),
        browser_p95_ms_max=optional_float(options.get("browser_p95_ms_max")),
    )
    alertable = ctx.alertable_domains
    routed = [violation for violation in violations if violation.domain in alertable]
    transition = ctx.observe_global("red", observed_ok=not routed, policy=policy)
    ctx.append_signal(
        "red", [cycle.started_ts, int(transition.effective_ok), len(routed)],
    )
    if transition.degraded and routed:
        evidence = _red_evidence(routed)
        ctx.events.append(
            "red_degraded",
            occurred_at=cycle.started_ts,
            violations=len(routed),
            domains=[violation.domain for violation in routed[:20]],
        )
        await ctx.alert(
            signal_alert(
                "Monitor warning: RED signals are degraded ⚠️",
                _red_details(routed),
                fail_streak=transition.fail_streak,
                down_after_failures=policy.down_after_failures,
            ),
        )
        if policy.dispatch_on_degraded:
            ctx.dispatch(
                Investigation(
                    state_key="service-monitoring.red",
                    title="RED signals investigation",
                    subject="RED error-rate or latency signals are degraded",
                    scope="Inspect recent requests, errors, and latency distributions for the affected domains.",
                ),
                evidence=cast("JsonValue", evidence),
            )
    if transition.recovered:
        ctx.events.append("red_recovered", occurred_at=cycle.started_ts)
        if policy.notify_on_recovery:
            await ctx.recovery(
                "RED signals recovered ✅ (error-rate/latency back under thresholds).",
            )
