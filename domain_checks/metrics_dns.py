from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DnsCheckResult:
    domain: str
    ok: bool
    a_records: list[str]
    aaaa_records: list[str]
    error: str | None
    drift_detected: bool
    expected_ips: list[str] | None


def _normalize_ip_list(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for x in items:
        s = str(x or "").strip()
        if s:
            out.append(s)
    return out


def _dns_query_sync(
    *,
    domain: str,
    record_type: str,
    resolvers: list[str] | None,
    timeout_seconds: float,
) -> list[str]:
    # dnspython is intentionally imported lazily to keep startup fast and to allow
    # running the monitor with DNS checks disabled.
    import dns.resolver  # type: ignore

    r = dns.resolver.Resolver(configure=True)
    if resolvers:
        r.nameservers = list(resolvers)
    r.timeout = max(0.5, float(timeout_seconds))
    r.lifetime = max(0.5, float(timeout_seconds))
    try:
        ans = r.resolve(domain, record_type)
    except dns.resolver.NoAnswer:
        # "NoAnswer" is a normal outcome (e.g. no AAAA record); treat it as empty.
        return []
    out: list[str] = []
    for rr in ans:
        s = str(rr or "").strip()
        if s:
            out.append(s)
    return out


async def check_dns(
    *,
    domains: list[str],
    resolvers: list[str] | None,
    timeout_seconds: float,
    require_ipv4: bool,
    require_ipv6: bool,
    previous_ips_by_domain: dict[str, list[str]] | None = None,
    expected_ips_by_domain: dict[str, list[str]] | None = None,
    alert_on_drift_by_domain: dict[str, bool] | None = None,
    concurrency: int = 50,
) -> list[DnsCheckResult]:
    sem = asyncio.Semaphore(max(1, int(concurrency)))
    prev = previous_ips_by_domain if isinstance(previous_ips_by_domain, dict) else {}
    expected = expected_ips_by_domain if isinstance(expected_ips_by_domain, dict) else {}
    drift_cfg = alert_on_drift_by_domain if isinstance(alert_on_drift_by_domain, dict) else {}

    async def _run_one(domain: str) -> DnsCheckResult:
        cleaned = str(domain or "").strip().lower()
        exp = _normalize_ip_list(expected.get(cleaned))
        prev_ips = set(_normalize_ip_list(prev.get(cleaned)))
        alert_on_drift = bool(drift_cfg.get(cleaned, False))

        a: list[str] = []
        aaaa: list[str] = []
        err = None

        async with sem:
            try:
                a = await asyncio.to_thread(
                    _dns_query_sync,
                    domain=cleaned,
                    record_type="A",
                    resolvers=resolvers,
                    timeout_seconds=float(timeout_seconds),
                )
            except Exception as exc:
                # Preserve error, but still try AAAA (helps distinguish partial resolver issues).
                err = f"A: {type(exc).__name__}: {exc}"
                a = []

            try:
                aaaa = await asyncio.to_thread(
                    _dns_query_sync,
                    domain=cleaned,
                    record_type="AAAA",
                    resolvers=resolvers,
                    timeout_seconds=float(timeout_seconds),
                )
            except Exception as exc:
                if err:
                    err = f"{err}; AAAA: {type(exc).__name__}: {exc}"
                else:
                    err = f"AAAA: {type(exc).__name__}: {exc}"
                aaaa = []

        a_set = set(_normalize_ip_list(a))
        aaaa_set = set(_normalize_ip_list(aaaa))
        cur_ips = a_set | aaaa_set

        ok = True
        if require_ipv4 and not a_set:
            ok = False
            if not err:
                err = "missing_A_record"
        if require_ipv6 and not aaaa_set:
            ok = False
            if err:
                err = f"{err}; missing_AAAA_record"
            else:
                err = "missing_AAAA_record"
        if not cur_ips:
            ok = False
            if not err:
                err = "no_dns_records"

        if exp:
            exp_set = set(exp)
            if not (cur_ips & exp_set):
                ok = False
                if err:
                    err = f"{err}; expected_ip_mismatch"
                else:
                    err = "expected_ip_mismatch"

        drift_detected = False
        if prev_ips and cur_ips and (cur_ips != prev_ips):
            drift_detected = True
            if alert_on_drift:
                ok = False
                if err:
                    err = f"{err}; drift_detected"
                else:
                    err = "drift_detected"

        return DnsCheckResult(
            domain=cleaned,
            ok=ok,
            a_records=sorted(a_set),
            aaaa_records=sorted(aaaa_set),
            error=err,
            drift_detected=drift_detected,
            expected_ips=(exp or None),
        )

    tasks = [asyncio.create_task(_run_one(d)) for d in domains]
    out: list[DnsCheckResult] = []
    for fut in asyncio.as_completed(tasks):
        out.append(await fut)
    out.sort(key=lambda x: x.domain)
    return out
