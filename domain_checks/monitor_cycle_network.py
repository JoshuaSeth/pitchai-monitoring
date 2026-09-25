# Copyright (c) 2026 PitchAI. All rights reserved.
"""Scheduled TLS certificate and DNS resolution monitor cycles."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, cast

from domain_checks.metrics_dns import check_dns
from domain_checks.metrics_tls import check_tls_certs
from domain_checks.monitor_alerts import signal_alert
from domain_checks.monitor_context import Investigation
from domain_checks.monitor_value_collections import bool_dict, string_list_dict
from domain_checks.monitor_values import json_float, string_list

if TYPE_CHECKING:
    from domain_checks.metrics_dns import DnsCheckResult
    from domain_checks.metrics_tls import TlsCertCheckResult
    from domain_checks.monitor_context import DomainCycle, MonitorContext
    from domain_checks.monitor_settings import FeaturePolicy
    from domain_checks.types import JsonObject, JsonValue


def _tls_evidence(results: list[TlsCertCheckResult]) -> list[JsonObject]:
    return [
        {
            "domain": result.domain,
            "ok": result.ok,
            "host": result.host,
            "port": result.port,
            "not_after_iso": result.not_after_iso,
            "days_remaining": result.days_remaining,
            "error": result.error,
            "details": result.details,
        }
        for result in results
    ]


def _tls_details(results: list[TlsCertCheckResult]) -> list[str]:
    details: list[str] = []
    for result in results:
        if not result.ok:
            remaining = (
                "n/a"
                if result.days_remaining is None
                else f"{result.days_remaining:.1f}d"
            )
            details.append(
                f"{result.domain}: remaining={remaining} error={result.error or 'threshold'}",
            )
    return details


async def _run_tls_checks(
    cycle: DomainCycle, policy: FeaturePolicy,
) -> list[TlsCertCheckResult]:
    urls = {spec.domain: spec.url for spec in cycle.enabled_specs}
    return await check_tls_certs(
        urls_by_domain=urls,
        min_days_valid=json_float(policy.options.get("min_days_valid", 14.0)),
        timeout_seconds=json_float(policy.options.get("timeout_seconds", 8.0)),
        concurrency=min(50, max(5, len(urls))),
    )


def _routed_failures[Result: (TlsCertCheckResult, DnsCheckResult)](
    ctx: MonitorContext, results: list[Result],
) -> list[Result]:
    inventory = ctx.settings.inventory.entries_by_domain
    external = [result for result in results if result.domain not in inventory]
    inventory_results = [result for result in results if result.domain in inventory]
    routed_inventory = [
        result for result in inventory_results if result.domain in ctx.alertable_domains
    ]
    return [result for result in [*external, *routed_inventory] if not result.ok]


async def run_tls_cycle(ctx: MonitorContext, cycle: DomainCycle) -> None:
    """Run due TLS checks and emit edge-triggered notices."""
    policy = ctx.settings.feature("tls")
    status = ctx.state.global_signals["tls"]
    now = time.time()
    if (
        not policy.enabled
        or not cycle.enabled_specs
        or now - status.last_run_ts < policy.interval_seconds
    ):
        return
    status.last_run_ts = now
    results = await _run_tls_checks(cycle, policy)
    failures = _routed_failures(ctx, results)
    transition = ctx.observe_global("tls", observed_ok=not failures, policy=policy)
    ctx.append_signal(
        "tls", [cycle.started_ts, int(transition.effective_ok), len(failures)],
    )
    if transition.degraded and failures:
        evidence = _tls_evidence(failures)
        ctx.events.append(
            "tls_degraded",
            occurred_at=cycle.started_ts,
            failures=len(failures),
            domains=[result.domain for result in failures[:20]],
        )
        await ctx.alert(
            signal_alert(
                "Monitor warning: TLS certificate checks are degraded ⚠️",
                _tls_details(failures),
                fail_streak=transition.fail_streak,
                down_after_failures=policy.down_after_failures,
            ),
        )
        if policy.dispatch_on_degraded:
            ctx.dispatch(
                Investigation(
                    state_key="service-monitoring.tls",
                    title="TLS investigation",
                    subject="TLS certificate checks are degraded",
                    scope="Inspect certificate chains, expiry, SNI, DNS, and listeners.",
                ),
                evidence=cast("JsonValue", evidence),
            )
    if transition.recovered:
        ctx.events.append("tls_recovered", occurred_at=cycle.started_ts)
        if policy.notify_on_recovery:
            await ctx.recovery("TLS checks recovered ✅ (certificate issues cleared).")


def _dns_evidence(results: list[DnsCheckResult]) -> list[JsonObject]:
    return [
        {
            "domain": result.domain,
            "ok": result.ok,
            "a_records": result.a_records,
            "aaaa_records": result.aaaa_records,
            "error": result.error,
            "drift_detected": result.drift_detected,
            "expected_ips": result.expected_ips,
        }
        for result in results
    ]


def _dns_details(results: list[DnsCheckResult]) -> list[str]:
    details: list[str] = []
    for result in results:
        if not result.ok:
            records = sorted(set(result.a_records + result.aaaa_records))
            details.append(
                f"{result.domain}: records={records} error={result.error or 'policy mismatch'}",
            )
    return details


def _dns_policy(
    policy: FeaturePolicy, domains: list[str],
) -> tuple[list[str] | None, dict[str, bool]]:
    options = policy.options
    resolvers = (
        string_list(options.get("resolvers"), description="dns.resolvers") or None
    )
    drift = {
        domain.lower(): bool(options.get("alert_on_drift", False)) for domain in domains
    }
    for domain, enabled in bool_dict(options.get("alert_on_drift_by_domain")).items():
        cleaned = domain.strip().lower()
        if cleaned:
            drift[cleaned] = enabled
    return resolvers, drift


async def _run_dns_checks(
    ctx: MonitorContext, cycle: DomainCycle, policy: FeaturePolicy,
) -> list[DnsCheckResult]:
    domains = [spec.domain for spec in cycle.enabled_specs]
    resolvers, drift = _dns_policy(policy, domains)
    options = policy.options
    results = await check_dns(
        domains=domains,
        resolvers=resolvers,
        timeout_seconds=json_float(options.get("timeout_seconds", 4.0)),
        require_ipv4=bool(options.get("require_ipv4", True)),
        require_ipv6=bool(options.get("require_ipv6", False)),
        previous_ips_by_domain=ctx.state.collections.dns_last_ips,
        expected_ips_by_domain=string_list_dict(options.get("expected_ips_by_domain")),
        alert_on_drift_by_domain=drift,
    )
    for result in results:
        records = set(result.a_records + result.aaaa_records)
        ctx.state.collections.dns_last_ips[result.domain] = sorted(records)
    return results


async def run_dns_cycle(ctx: MonitorContext, cycle: DomainCycle) -> None:
    """Run due DNS checks and emit edge-triggered notices."""
    policy = ctx.settings.feature("dns")
    status = ctx.state.global_signals["dns"]
    now = time.time()
    if (
        not policy.enabled
        or not cycle.enabled_specs
        or now - status.last_run_ts < policy.interval_seconds
    ):
        return
    status.last_run_ts = now
    results = await _run_dns_checks(ctx, cycle, policy)
    failures = _routed_failures(ctx, results)
    transition = ctx.observe_global("dns", observed_ok=not failures, policy=policy)
    ctx.append_signal(
        "dns", [cycle.started_ts, int(transition.effective_ok), len(failures)],
    )
    if transition.degraded and failures:
        evidence = _dns_evidence(failures)
        ctx.events.append(
            "dns_degraded",
            occurred_at=cycle.started_ts,
            failures=len(failures),
            domains=[result.domain for result in failures[:20]],
        )
        await ctx.alert(
            signal_alert(
                "Monitor warning: DNS checks are degraded ⚠️",
                _dns_details(failures),
                fail_streak=transition.fail_streak,
                down_after_failures=policy.down_after_failures,
            ),
        )
        if policy.dispatch_on_degraded:
            ctx.dispatch(
                Investigation(
                    state_key="service-monitoring.dns",
                    title="DNS investigation",
                    subject="DNS resolution or address policy checks are degraded",
                    scope=(
                        "Inspect authoritative records, recursive resolution, "
                        "address drift, and configured expectations."
                    ),
                ),
                evidence=cast("JsonValue", evidence),
            )
    if transition.recovered:
        ctx.events.append("dns_recovered", occurred_at=cycle.started_ts)
        if policy.notify_on_recovery:
            await ctx.recovery("DNS checks recovered ✅ (resolution issues cleared).")
