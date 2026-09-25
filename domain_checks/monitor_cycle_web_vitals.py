# Copyright (c) 2026 PitchAI. All rights reserved.
"""Per-domain Core Web Vitals monitor cycle."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from domain_checks.metrics_web_vitals import WebVitalsResult, measure_web_vitals
from domain_checks.monitor_alerts import signal_alert
from domain_checks.monitor_context import Investigation
from domain_checks.monitor_values import int_value, json_float, optional_float

if TYPE_CHECKING:
    from playwright.async_api import Browser

    from domain_checks.common_check import DomainCheckSpec
    from domain_checks.monitor_context import DomainCycle, MonitorContext
    from domain_checks.monitor_settings import FeaturePolicy
    from domain_checks.types import JsonObject, JsonValue


@dataclass(frozen=True)
class VitalThresholds:
    """Optional Core Web Vitals failure thresholds."""

    lcp_ms: float | None
    cls: float | None
    inp_ms: float | None


def _thresholds(spec: DomainCheckSpec, policy: FeaturePolicy) -> VitalThresholds:
    options = policy.options
    config = spec.web_vitals
    return VitalThresholds(
        lcp_ms=optional_float(config.get("lcp_ms_max", options.get("lcp_ms_max"))),
        cls=optional_float(config.get("cls_max", options.get("cls_max"))),
        inp_ms=optional_float(config.get("inp_ms_max", options.get("inp_ms_max"))),
    )


def _evaluated(result: WebVitalsResult, thresholds: VitalThresholds) -> WebVitalsResult:
    if not result.ok:
        return result
    metrics = result.metrics
    violations: list[str] = []
    lcp = metrics.get("lcp_ms")
    if thresholds.lcp_ms is not None and lcp is not None and json_float(lcp) > thresholds.lcp_ms:
        violations.append(f"lcp_ms>{thresholds.lcp_ms:.0f}")
    cls = metrics.get("cls")
    if thresholds.cls is not None and cls is not None and json_float(cls) > thresholds.cls:
        violations.append(f"cls>{thresholds.cls:.3f}")
    inp = metrics.get("inp_ms")
    if thresholds.inp_ms is not None and inp is not None and json_float(inp) > thresholds.inp_ms:
        violations.append(f"inp_ms>{thresholds.inp_ms:.0f}")
    if not violations:
        return result
    return WebVitalsResult(
        domain=result.domain,
        ok=False,
        metrics=result.metrics,
        error="threshold_exceeded: " + ",".join(violations),
        elapsed_ms=result.elapsed_ms,
        browser_infra_error=result.browser_infra_error,
    )


def _evidence(results: list[WebVitalsResult]) -> list[JsonObject]:
    return [
        {
            "domain": result.domain,
            "metrics": result.metrics,
            "error": result.error,
            "elapsed_ms": result.elapsed_ms,
            "browser_infra_error": result.browser_infra_error,
        }
        for result in results
    ]


def _details(results: list[WebVitalsResult]) -> list[str]:
    details: list[str] = []
    for result in results:
        metrics = result.metrics
        readings = [
            f"LCP={metrics.get('lcp_ms')}",
            f"CLS={metrics.get('cls')}",
            f"INP={metrics.get('inp_ms')}",
        ]
        details.append(f"{result.domain}: {' '.join(readings)} error={result.error or 'threshold'}")
    return details


def _due_specs(
    ctx: MonitorContext,
    cycle: DomainCycle,
    policy: FeaturePolicy,
    now: float,
) -> list[DomainCheckSpec]:
    status = ctx.state.per_domain_signals["web_vitals"]
    due = [
        spec
        for spec in cycle.enabled_specs
        if now - status.last_run_ts.get(spec.domain, 0.0) >= policy.interval_seconds
    ]
    due.sort(key=lambda spec: status.last_run_ts.get(spec.domain, 0.0))
    maximum = max(1, int_value(policy.options.get("max_domains_per_cycle"), default=1))
    return due[:maximum]


async def _handle_result(
    ctx: MonitorContext,
    cycle: DomainCycle,
    policy: FeaturePolicy,
    result: WebVitalsResult,
) -> WebVitalsResult | None:
    transition = ctx.observe_domain("web_vitals", result.domain, observed_ok=result.ok, policy=policy)
    entry = ctx.settings.inventory.entries_by_domain[result.domain]
    if transition.degraded and not result.ok:
        ctx.events.append(
            "web_vitals_degraded",
            occurred_at=cycle.started_ts,
            domain=result.domain,
            reason=str(result.error or "threshold_exceeded")[:500],
            telegram_alert=entry.routes_telegram,
            alert_policy=entry.alert_policy.telegram,
        )
        if entry.routes_telegram:
            await ctx.alert(
                signal_alert(
                    f"Monitor warning: Core Web Vitals degraded for {result.domain} ⚠️",
                    _details([result]),
                    fail_streak=transition.fail_streak,
                    down_after_failures=policy.down_after_failures,
                ),
            )
            return result
    if transition.recovered:
        ctx.events.append("web_vitals_recovered", occurred_at=cycle.started_ts, domain=result.domain)
        if policy.notify_on_recovery and entry.routes_telegram:
            await ctx.recovery(f"Web vitals recovered ✅ domain={result.domain}")
    return None


async def run_web_vitals_cycle(
    ctx: MonitorContext,
    cycle: DomainCycle,
    browser: Browser | None,
) -> None:
    """Measure due domains when browser infrastructure is available."""
    policy = ctx.settings.feature("web_vitals")
    if not policy.enabled or browser is None or cycle.browser_degraded:
        return
    now = time.time()
    status = ctx.state.per_domain_signals["web_vitals"]
    dispatch_failures: list[WebVitalsResult] = []
    for spec in _due_specs(ctx, cycle, policy, now):
        status.last_run_ts[spec.domain] = now
        result = await measure_web_vitals(
            domain=spec.domain,
            url=spec.url,
            browser=browser,
            timeout_seconds=json_float(policy.options.get("timeout_seconds", 45.0)),
            post_load_wait_ms=int_value(policy.options.get("post_load_wait_ms"), default=4500),
        )
        if not result.ok and result.browser_infra_error:
            continue
        failure = await _handle_result(ctx, cycle, policy, _evaluated(result, _thresholds(spec, policy)))
        if failure is not None:
            dispatch_failures.append(failure)
    if dispatch_failures and policy.dispatch_on_degraded:
        evidence = _evidence(dispatch_failures)
        ctx.dispatch(
            Investigation(
                state_key="service-monitoring.web-vitals",
                title="Web vitals investigation",
                subject="Core Web Vitals exceed configured thresholds",
                scope="Inspect browser timing, backend latency, assets, render blocking, and layout-shift evidence.",
            ),
            evidence=cast("JsonValue", evidence),
        )
