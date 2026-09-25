# Copyright (c) 2026 PitchAI. All rights reserved.
"""Per-domain browser synthetic-transaction monitor cycle."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, cast

from domain_checks.metrics_synthetic import run_synthetic_transactions
from domain_checks.monitor_alerts import signal_alert
from domain_checks.monitor_context import Investigation
from domain_checks.monitor_values import int_value, json_float

if TYPE_CHECKING:
    from playwright.async_api import Browser

    from domain_checks.common_check import DomainCheckSpec
    from domain_checks.monitor_context import DomainCycle, MonitorContext
    from domain_checks.monitor_settings import FeaturePolicy
    from domain_checks.synthetic_models import SyntheticTransactionResult
    from domain_checks.types import JsonObject, JsonValue


def _evidence(results: list[SyntheticTransactionResult]) -> list[JsonObject]:
    return [
        {
            "domain": result.domain,
            "name": result.name,
            "elapsed_ms": result.elapsed_ms,
            "error": result.error,
            "details": result.details,
            "browser_infra_error": result.browser_infra_error,
        }
        for result in results
    ]


def _details(results: list[SyntheticTransactionResult]) -> list[str]:
    details: list[str] = []
    for result in results:
        elapsed = "n/a" if result.elapsed_ms is None else f"{round(result.elapsed_ms)}ms"
        error = (result.error or "transaction_failed").strip()[:260]
        details.append(f"{result.domain} [{result.name}]: {error} ({elapsed})")
    return details


def _due_specs(
    ctx: MonitorContext,
    cycle: DomainCycle,
    policy: FeaturePolicy,
    now: float,
) -> list[DomainCheckSpec]:
    status = ctx.state.per_domain_signals["synthetic"]
    configured = [spec for spec in cycle.enabled_specs if spec.synthetic_transactions]
    due = [spec for spec in configured if now - status.last_run_ts.get(spec.domain, 0.0) >= policy.interval_seconds]
    due.sort(key=lambda spec: status.last_run_ts.get(spec.domain, 0.0))
    maximum = max(1, int_value(policy.options.get("max_domains_per_cycle"), default=1))
    return due[:maximum]


async def _handle_results(
    ctx: MonitorContext,
    cycle: DomainCycle,
    policy: FeaturePolicy,
    domain: str,
    results: list[SyntheticTransactionResult],
) -> list[SyntheticTransactionResult]:
    failures = [result for result in results if not result.ok]
    real_failures = [result for result in failures if not result.browser_infra_error]
    transition = ctx.observe_domain("synthetic", domain, observed_ok=not real_failures, policy=policy)
    entry = ctx.settings.inventory.entries_by_domain[domain]
    if transition.degraded and real_failures:
        ctx.events.append(
            "synthetic_degraded",
            occurred_at=cycle.started_ts,
            domain=domain,
            failures=len(real_failures),
            telegram_alert=entry.routes_telegram,
            alert_policy=entry.alert_policy.telegram,
        )
        if entry.routes_telegram:
            await ctx.alert(
                signal_alert(
                    f"Monitor warning: Synthetic transactions degraded for {domain} ⚠️",
                    _details(real_failures),
                    fail_streak=transition.fail_streak,
                    down_after_failures=policy.down_after_failures,
                ),
            )
            return real_failures
    if transition.recovered:
        ctx.events.append("synthetic_recovered", occurred_at=cycle.started_ts, domain=domain)
        if policy.notify_on_recovery and entry.routes_telegram:
            await ctx.recovery(f"Synthetic transactions recovered ✅ domain={domain}")
    return []


async def run_synthetic_cycle(
    ctx: MonitorContext,
    cycle: DomainCycle,
    browser: Browser | None,
) -> None:
    """Run due synthetic transactions when browser infrastructure is available."""
    policy = ctx.settings.feature("synthetic")
    if not policy.enabled or browser is None or cycle.browser_degraded:
        return
    now = time.time()
    timeout = json_float(policy.options.get("timeout_seconds", 35.0))
    status = ctx.state.per_domain_signals["synthetic"]
    dispatch_failures: list[SyntheticTransactionResult] = []
    for spec in _due_specs(ctx, cycle, policy, now):
        status.last_run_ts[spec.domain] = now
        results = await run_synthetic_transactions(
            domain=spec.domain,
            base_url=spec.url,
            browser=browser,
            transactions=spec.synthetic_transactions,
            timeout_seconds=timeout,
        )
        dispatch_failures.extend(await _handle_results(ctx, cycle, policy, spec.domain, results))
    if dispatch_failures and policy.dispatch_on_degraded:
        evidence = _evidence(dispatch_failures)
        ctx.dispatch(
            Investigation(
                state_key="service-monitoring.synthetic",
                title="Synthetic transactions investigation",
                subject="browser synthetic transaction flows are degraded",
                scope="Inspect the failing UI flow, frontend, APIs, authentication, proxy, and container evidence.",
            ),
            evidence=cast("JsonValue", evidence),
        )
