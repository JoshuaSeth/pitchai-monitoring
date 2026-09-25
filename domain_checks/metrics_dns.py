# Copyright (c) 2026 PitchAI. All rights reserved.
"""DNS availability and address-drift monitoring."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, NamedTuple, NotRequired, TypedDict, Unpack, cast

import dns.exception
import dns.resolver

if TYPE_CHECKING:
    from collections.abc import Sequence


class DnsCheckResult(NamedTuple):
    """Represent one domain's DNS check outcome."""

    domain: str
    ok: bool
    a_records: list[str]
    aaaa_records: list[str]
    error: str | None
    drift_detected: bool
    expected_ips: list[str] | None


class DnsCheckOptions(TypedDict):
    """Keyword controls accepted by DNS checks."""

    resolvers: list[str] | None
    timeout_seconds: float
    require_ipv4: bool
    require_ipv6: bool
    previous_ips_by_domain: NotRequired[dict[str, list[str]] | None]
    expected_ips_by_domain: NotRequired[dict[str, list[str]] | None]
    alert_on_drift_by_domain: NotRequired[dict[str, bool] | None]
    concurrency: NotRequired[int]


class _DnsContext(NamedTuple):
    resolvers: list[str] | None
    timeout_seconds: float
    require_ipv4: bool
    require_ipv6: bool
    previous_ips: dict[str, list[str]]
    expected_ips: dict[str, list[str]]
    drift_alerts: dict[str, bool]
    semaphore: asyncio.Semaphore


class _DnsRecords(NamedTuple):
    ipv4: list[str]
    ipv6: list[str]
    error: str | None


def _normalize_ip_list(items: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for item in items or []:
        address = str(item or "").strip()
        if address:
            normalized.append(address)
    return normalized


def _dns_query_sync(
    *,
    domain: str,
    record_type: str,
    resolvers: list[str] | None,
    timeout_seconds: float,
) -> list[str]:
    resolver = dns.resolver.Resolver(configure=True)
    if resolvers:
        resolver.nameservers = list(resolvers)
    resolver.timeout = max(0.5, float(timeout_seconds))
    resolver.lifetime = max(0.5, float(timeout_seconds))
    try:
        answer = resolver.resolve(domain, record_type)
    except dns.resolver.NoAnswer:
        return []
    records: list[str] = []
    answer_records = cast("Sequence[object]", cast("object", answer.rrset or ()))
    for record in answer_records:
        value = str(record or "").strip()
        if value:
            records.append(value)
    return records


async def _query_record(
    domain: str,
    record_type: str,
    context: _DnsContext,
) -> tuple[list[str], str | None]:
    try:
        return (
            await asyncio.to_thread(
                _dns_query_sync,
                domain=domain,
                record_type=record_type,
                resolvers=context.resolvers,
                timeout_seconds=context.timeout_seconds,
            ),
            None,
        )
    except (dns.exception.DNSException, OSError) as exc:
        return [], f"{record_type}: {type(exc).__name__}: {exc}"


async def _query_records(domain: str, context: _DnsContext) -> _DnsRecords:
    async with context.semaphore:
        ipv4, ipv4_error = await _query_record(domain, "A", context)
        ipv6, ipv6_error = await _query_record(domain, "AAAA", context)
    error = ipv4_error
    if ipv6_error:
        error = f"{error}; {ipv6_error}" if error else ipv6_error
    return _DnsRecords(ipv4, ipv6, error)


def _required_records_error(
    ipv4: set[str],
    ipv6: set[str],
    context: _DnsContext,
    initial_error: str | None,
) -> tuple[bool, str | None]:
    ok = True
    error = initial_error
    if context.require_ipv4 and not ipv4:
        ok = False
        error = error or "missing_A_record"
    if context.require_ipv6 and not ipv6:
        ok = False
        error = f"{error}; missing_AAAA_record" if error else "missing_AAAA_record"
    if not ipv4 and not ipv6:
        ok = False
        error = error or "no_dns_records"
    return ok, error


def _expected_ip_error(
    current_ips: set[str],
    expected_ips: list[str],
    error: str | None,
) -> str | None:
    if expected_ips and not current_ips.intersection(expected_ips):
        return f"{error}; expected_ip_mismatch" if error else "expected_ip_mismatch"
    return error


def _drift_outcome(
    current_ips: set[str],
    previous_ips: set[str],
    error: str | None,
    *,
    alert_on_drift: bool,
) -> tuple[bool, str | None]:
    drift_detected = bool(previous_ips and current_ips and current_ips != previous_ips)
    if drift_detected and alert_on_drift:
        error = f"{error}; drift_detected" if error else "drift_detected"
    return drift_detected, error


async def _check_domain(domain: str, context: _DnsContext) -> DnsCheckResult:
    cleaned_domain = str(domain or "").strip().lower()
    records = await _query_records(cleaned_domain, context)
    ipv4 = set(_normalize_ip_list(records.ipv4))
    ipv6 = set(_normalize_ip_list(records.ipv6))
    current_ips = ipv4 | ipv6
    expected_ips = _normalize_ip_list(context.expected_ips.get(cleaned_domain))
    previous_ips = set(_normalize_ip_list(context.previous_ips.get(cleaned_domain)))
    ok, error = _required_records_error(ipv4, ipv6, context, records.error)
    expected_error = _expected_ip_error(current_ips, expected_ips, error)
    if expected_error != error:
        ok = False
    drift_detected, drift_error = _drift_outcome(
        current_ips,
        previous_ips,
        expected_error,
        alert_on_drift=bool(context.drift_alerts.get(cleaned_domain, False)),
    )
    if drift_error != expected_error:
        ok = False
    return DnsCheckResult(
        domain=cleaned_domain,
        ok=ok,
        a_records=sorted(ipv4),
        aaaa_records=sorted(ipv6),
        error=drift_error,
        drift_detected=drift_detected,
        expected_ips=expected_ips or None,
    )


async def check_dns(
    *,
    domains: list[str],
    **options: Unpack[DnsCheckOptions],
) -> list[DnsCheckResult]:
    """Check DNS records and configured address expectations concurrently.

    Returns:
        DNS outcomes ordered by domain.
    """
    context = _DnsContext(
        resolvers=options["resolvers"],
        timeout_seconds=float(options["timeout_seconds"]),
        require_ipv4=options["require_ipv4"],
        require_ipv6=options["require_ipv6"],
        previous_ips=options.get("previous_ips_by_domain") or {},
        expected_ips=options.get("expected_ips_by_domain") or {},
        drift_alerts=options.get("alert_on_drift_by_domain") or {},
        semaphore=asyncio.Semaphore(max(1, int(options.get("concurrency", 50)))),
    )
    tasks = [asyncio.create_task(_check_domain(domain, context)) for domain in domains]
    completed_tasks = asyncio.as_completed(tasks)
    results = [await future for future in completed_tasks]
    results.sort(key=lambda result: result.domain)
    return results
