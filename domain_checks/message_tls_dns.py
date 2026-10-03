# Copyright (c) 2026 PitchAI. All rights reserved.
"""Pure existing monitor text construction; no delivery or observation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .message_templates import dispatch_read_only_rules as _dispatch_read_only_rules

if TYPE_CHECKING:
    from .metrics_dns import DnsCheckResult
    from .metrics_tls import TlsCertCheckResult


def build_tls_alert_message(
    *,
    results: list[TlsCertCheckResult],
    min_days_valid: float,
    down_after_failures: int,
    fail_streak: int,
) -> str:
    """Return the existing bounded message without invoking a transport."""
    bad = [r for r in results if not r.ok]
    lines = ["Monitor warning: TLS certificate checks are degraded ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.extend((f"Threshold: min_days_valid={float(min_days_valid):.1f}d", ""))
    for r in bad[:15]:
        host = r.host or "?"
        port = r.port or 443
        days = "n/a" if r.days_remaining is None else f"{r.days_remaining:.2f}d"
        err = (r.error or "unknown").strip()
        lines.append(f"- {r.domain}: {err} host={host}:{port} days_remaining={days} not_after={r.not_after_iso}")
    return "\n".join(lines).strip()


def build_tls_dispatch_prompt(*, results: list[TlsCertCheckResult], min_days_valid: float) -> str:
    """Return the existing bounded message without invoking a transport."""
    bad = [r for r in results if not r.ok]
    payload = [
        {
            "domain": r.domain,
            "host": r.host,
            "port": r.port,
            "not_after_iso": r.not_after_iso,
            "days_remaining": r.days_remaining,
            "error": r.error,
            "details": r.details,
        }
        for r in bad[:20]
    ]
    details = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "The service-monitoring detected TLS certificate problems (expiry soon / handshake failures).\n\n"
        f"Threshold: min_days_valid={float(min_days_valid):.1f} days\n\n"
        "Failing TLS checks (JSON):\n"
        f"{details}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Confirm certificate status from the production host with openssl s_client / curl -Iv.\n"
        "2) If expiry is near, check certbot/Let's Encrypt renewal status and Nginx config for the affected domain.\n"
        "3) Identify whether the issue is DNS/SNI mismatch, expired cert, wrong cert installed, or renewal failure.\n"
        "4) Provide a clear remediation plan for a human operator (avoid making changes).\n\n"
        "Return a concise final report with:\n"
        "- Root cause + evidence\n"
        "- Affected domains + expiry dates\n"
        "- Recommended safe remediation steps\n"
    )


def build_dns_alert_message(
    *,
    results: list[DnsCheckResult],
    down_after_failures: int,
    fail_streak: int,
) -> str:
    """Return the existing bounded message without invoking a transport."""
    bad = [r for r in results if not r.ok]
    lines = ["Monitor warning: DNS checks are degraded ⚠️"]
    if down_after_failures > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after_failures}")
    lines.append("")
    for r in bad[:15]:
        a = ",".join(r.a_records[:4]) if r.a_records else "-"
        aaaa = ",".join(r.aaaa_records[:4]) if r.aaaa_records else "-"
        drift = " drift" if r.drift_detected else ""
        exp = ",".join((r.expected_ips or [])[:4]) if r.expected_ips else "-"
        err = (r.error or "").strip()
        extra = f" error={err}" if err else ""
        lines.append(f"- {r.domain}:{drift} A=[{a}] AAAA=[{aaaa}] expected=[{exp}]{extra}")
    return "\n".join(lines).strip()


def build_dns_dispatch_prompt(*, results: list[DnsCheckResult]) -> str:
    """Return the existing bounded message without invoking a transport."""
    bad = [r for r in results if not r.ok]
    payload = [
        {
            "domain": r.domain,
            "a_records": r.a_records,
            "aaaa_records": r.aaaa_records,
            "drift_detected": r.drift_detected,
            "expected_ips": r.expected_ips,
            "error": r.error,
        }
        for r in bad[:25]
    ]
    details = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        "The service-monitoring detected DNS resolution problems (NXDOMAIN/timeout/no A/AAAA or drift).\n\n"
        "Failing DNS checks (JSON):\n"
        f"{details}\n\n"
        f"{_dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Confirm DNS resolution from the production host using dig/host/nslookup against multiple resolvers.\n"
        "2) Determine whether the issue is authoritative DNS, resolver, DNSSEC, or transient network.\n"
        "3) If drift is flagged, assess whether the change is expected (deploy/failover) or suspicious.\n"
        "4) Provide a human-safe remediation plan (no changes executed).\n\n"
        "Return a concise final report with:\n"
        "- Root cause + evidence\n"
        "- Affected domains + observed records\n"
        "- Recommended safe remediation steps\n"
    )
