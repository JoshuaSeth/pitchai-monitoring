# Copyright (c) 2026 PitchAI. All rights reserved.
"""Primary domain checks, transitions, alerts, and rolling history."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
from playwright.async_api import Error as PlaywrightError

from domain_checks.common_check import DomainCheckResult
from domain_checks.history import append_sample, prune_history
from domain_checks.monitor_alerts import domain_down_alert
from domain_checks.monitor_context import DomainCycle, Investigation
from domain_checks.monitor_domains import format_disabled_domain_line
from domain_checks.monitor_time import load_timezone
from domain_checks.monitor_values import object_config, optional_float

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from playwright.async_api import Browser

    from domain_checks.common_check import DomainCheckSpec
    from domain_checks.monitor_context import MonitorContext

    DomainChecker = Callable[
        [DomainCheckSpec, httpx.AsyncClient, Browser | None, asyncio.Semaphore],
        Awaitable[DomainCheckResult],
    ]

LOGGER = logging.getLogger("service-monitoring")


@dataclass(frozen=True)
class DomainResources:
    """Browser and concurrency dependencies for primary domain checks."""

    browser: Browser | None
    checker: DomainChecker
    check_semaphore: asyncio.Semaphore
    browser_semaphore: asyncio.Semaphore


async def _checked(
    ctx: MonitorContext, spec: DomainCheckSpec, resources: DomainResources,
) -> DomainCheckResult:
    try:
        return await _invoke_check(ctx, spec, resources)
    except (
        httpx.HTTPError,
        PlaywrightError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        error = f"{type(exc).__name__}: {exc}"
        LOGGER.exception("Domain check crashed domain=%s error=%s", spec.domain, error)
        return DomainCheckResult(
            domain=spec.domain,
            ok=False,
            reason="check_crashed",
            details={"error": error},
        )


async def _invoke_check(
    ctx: MonitorContext, spec: DomainCheckSpec, resources: DomainResources,
) -> DomainCheckResult:
    async with resources.check_semaphore:
        return await resources.checker(
            spec,
            ctx.http_client,
            resources.browser,
            resources.browser_semaphore,
        )


def _disabled_inventory(
    ctx: MonitorContext, now_ts: float,
) -> tuple[list[DomainCheckSpec], list[str]]:
    disabled = [
        entry for entry in ctx.settings.inventory.entries if entry.is_disabled(now_ts)
    ]
    disabled_domains = {entry.domain for entry in disabled}
    for domain in disabled_domains:
        ctx.state.domains.remove(domain)
        _ = ctx.state.history.pop(domain, None)
        for status in ctx.state.per_domain_signals.values():
            status.remove(domain)
        _ = ctx.state.collections.dns_last_ips.pop(domain, None)
    heartbeat = object_config(ctx.settings.config, "heartbeat")
    timezone = load_timezone(str(heartbeat.get("timezone") or "UTC"))
    lines = [format_disabled_domain_line(entry, timezone) for entry in disabled]
    inventory_entries = ctx.settings.inventory.entries
    enabled_entries = [entry for entry in inventory_entries if entry.domain not in disabled_domains]
    specs_by_domain = ctx.settings.inventory.specs_by_domain
    enabled = [specs_by_domain[entry.domain] for entry in enabled_entries]
    LOGGER.debug("Domain inventory disabled=%s", sorted(disabled_domains))
    return enabled, sorted(lines)


async def _transition(
    ctx: MonitorContext, result: DomainCheckResult, started_ts: float,
) -> None:
    core = ctx.settings.core
    domain = result.domain
    previous = ctx.state.domains.last_ok.get(domain, True)
    degraded, recovered = ctx.state.domains.observe(
        domain,
        observed_ok=result.ok,
        down_after=core.down_after_failures,
        up_after=core.up_after_successes,
    )
    if degraded:
        entry = ctx.settings.inventory.entries_by_domain[domain]
        details = result.details
        error = details.get("error")
        ctx.events.append(
            "domain_down",
            occurred_at=started_ts,
            domain=domain,
            reason=result.reason,
            status_code=details.get("status_code"),
            error=error[:800] if isinstance(error, str) else None,
            fail_streak=ctx.state.domains.fail_streak[domain],
            telegram_alert=entry.routes_telegram,
            alert_policy=entry.alert_policy.telegram,
        )
        enriched = DomainCheckResult(
            domain=domain,
            ok=result.ok,
            reason=result.reason,
            details={
                **details,
                "fail_streak": ctx.state.domains.fail_streak[domain],
                "down_after_failures": core.down_after_failures,
            },
        )
        if entry.routes_telegram:
            await ctx.alert(domain_down_alert(enriched))
            ctx.dispatch(
                Investigation(
                    state_key=domain,
                    title=f"{domain} investigation",
                    subject=f"domain {domain} is down ({result.reason})",
                    scope=f"Inspect DNS, TLS, HTTP, browser assertions, reverse proxy, and containers for {domain}.",
                ),
                evidence=details,
            )
        return
    if recovered:
        ctx.events.append("domain_up", occurred_at=started_ts, domain=domain)
    level = logging.INFO if result.ok else logging.WARNING
    LOGGER.log(
        level,
        "Domain result domain=%s ok=%s effective_ok=%s previous_ok=%s reason=%s details=%s",
        domain,
        result.ok,
        ctx.state.domains.last_ok[domain],
        previous,
        result.reason,
        result.details,
    )


def _record_history(ctx: MonitorContext, cycle: DomainCycle) -> None:
    for domain, result in cycle.results.items():
        details = result.details
        status_value = details.get("status_code")
        status_code = int(status_value) if isinstance(status_value, int) else None
        append_sample(
            ctx.state.history,
            domain=domain,
            ts=cycle.started_ts,
            ok=ctx.state.domains.last_ok.get(domain, result.ok),
            http_elapsed_ms=optional_float(details.get("http_elapsed_ms")),
            browser_elapsed_ms=optional_float(details.get("browser_elapsed_ms")),
            status_code=status_code,
        )
    prune_history(
        ctx.state.history,
        before_ts=time.time() - ctx.settings.core.history_retention_seconds,
    )


async def run_domain_cycle(
    ctx: MonitorContext, resources: DomainResources,
) -> DomainCycle:
    """Run every enabled primary domain check and persist its transition.

    Returns:
        The primary-domain evidence for downstream feature cycles.
    """
    started_ts = time.time()
    enabled_specs, disabled_lines = _disabled_inventory(ctx, started_ts)
    tasks = [
        asyncio.create_task(_checked(ctx, spec, resources)) for spec in enabled_specs
    ]
    results: dict[str, DomainCheckResult] = {}
    browser_degraded = False
    for task in asyncio.as_completed(tasks):
        result = await task
        results[result.domain] = result
        browser_degraded = browser_degraded or bool(
            result.details.get("browser_infra_error"),
        )
        await _transition(ctx, result, started_ts)
    cycle = DomainCycle(
        started_ts=started_ts,
        results=results,
        enabled_specs=enabled_specs,
        disabled_lines=disabled_lines,
        browser_degraded=browser_degraded,
    )
    _record_history(ctx, cycle)
    return cycle
