# Copyright (c) 2026 PitchAI. All rights reserved.
"""Per-domain API contract monitor cycle."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, cast

from domain_checks.metrics_api_contract import run_api_contract_checks
from domain_checks.monitor_alerts import signal_alert
from domain_checks.monitor_context import Investigation
from domain_checks.monitor_values import json_float

if TYPE_CHECKING:
    from domain_checks.api_contract_models import ApiContractCheckResult
    from domain_checks.common_check import DomainCheckSpec
    from domain_checks.monitor_context import DomainCycle, MonitorContext
    from domain_checks.monitor_settings import FeaturePolicy
    from domain_checks.types import JsonObject, JsonValue

_MAX_API_DOMAINS = 50


def _evidence(results: list[ApiContractCheckResult]) -> list[JsonObject]:
    return [
        {
            "domain": result.domain,
            "name": result.name,
            "ok": result.ok,
            "url": result.url,
            "status_code": result.status_code,
            "elapsed_ms": result.elapsed_ms,
            "error": result.error,
            "details": result.details,
        }
        for result in results
    ]


def _details(results: list[ApiContractCheckResult]) -> list[str]:
    return [
        (
            f"{result.domain} [{result.name}]: status={result.status_code} "
            f"elapsed={result.elapsed_ms}ms error={result.error or 'contract mismatch'}"
        )
        for result in results
    ]


async def _handle_domain(
    ctx: MonitorContext,
    cycle: DomainCycle,
    policy: FeaturePolicy,
    domain: str,
    results: list[ApiContractCheckResult],
) -> list[ApiContractCheckResult]:
    failures = [result for result in results if not result.ok]
    transition = ctx.observe_domain(
        "api_contract", domain, observed_ok=not failures, policy=policy,
    )
    entry = ctx.settings.inventory.entries_by_domain[domain]
    if transition.degraded:
        ctx.events.append(
            "api_contract_degraded",
            occurred_at=cycle.started_ts,
            domain=domain,
            failures=len(failures),
            telegram_alert=entry.routes_telegram,
            alert_policy=entry.alert_policy.telegram,
        )
        if entry.routes_telegram:
            await ctx.alert(
                signal_alert(
                    f"Monitor warning: API contract checks degraded for {domain} ⚠️",
                    _details(failures),
                    fail_streak=transition.fail_streak,
                    down_after_failures=policy.down_after_failures,
                ),
            )
            return failures
    if transition.recovered:
        ctx.events.append(
            "api_contract_recovered", occurred_at=cycle.started_ts, domain=domain,
        )
        if policy.notify_on_recovery and entry.routes_telegram:
            await ctx.recovery(f"API contract checks recovered ✅ domain={domain}")
    return []


def _due_specs(
    cycle: DomainCycle, policy: FeaturePolicy, now: float, ctx: MonitorContext,
) -> list[DomainCheckSpec]:
    status = ctx.state.per_domain_signals["api_contract"]
    due: list[DomainCheckSpec] = []
    for spec in cycle.enabled_specs:
        last_run = status.last_run_ts.get(spec.domain, 0.0)
        if spec.api_contract_checks and now - last_run >= policy.interval_seconds:
            due.append(spec)
    return due[:_MAX_API_DOMAINS]


async def run_api_cycle(ctx: MonitorContext, cycle: DomainCycle) -> None:
    """Run due per-domain API contracts and emit edge-triggered notices."""
    policy = ctx.settings.feature("api_contract")
    if not policy.enabled or not cycle.enabled_specs:
        return
    now = time.time()
    due = _due_specs(cycle, policy, now, ctx)
    status = ctx.state.per_domain_signals["api_contract"]
    timeout = json_float(policy.options.get("timeout_seconds", 10.0))
    tasks: dict[str, asyncio.Task[list[ApiContractCheckResult]]] = {}
    for spec in due:
        status.last_run_ts[spec.domain] = now
        check = run_api_contract_checks(
            http_client=ctx.http_client,
            domain=spec.domain,
            base_url=spec.url,
            checks=spec.api_contract_checks,
            timeout_seconds=timeout,
        )
        tasks[spec.domain] = asyncio.create_task(check)
    dispatch_failures: list[ApiContractCheckResult] = []
    for domain, task in tasks.items():
        results = await task
        dispatch_failures.extend(
            await _handle_domain(ctx, cycle, policy, domain, results),
        )
    if dispatch_failures and policy.dispatch_on_degraded:
        evidence = _evidence(dispatch_failures)
        ctx.dispatch(
            Investigation(
                state_key="service-monitoring.api-contract",
                title="API contract investigation",
                subject="API contract checks are degraded",
                scope="Inspect API status, response schema, content type, latency, and authentication behavior.",
            ),
            evidence=cast("JsonValue", evidence),
        )
