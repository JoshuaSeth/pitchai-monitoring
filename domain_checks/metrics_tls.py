from __future__ import annotations

import asyncio
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class TlsCertCheckResult:
    domain: str
    ok: bool
    host: str | None
    port: int | None
    not_after_iso: str | None
    days_remaining: float | None
    error: str | None
    details: dict[str, Any]


def _tls_host_port_from_url(url: str) -> tuple[str, int] | None:
    try:
        parts = urlsplit(str(url or "").strip())
    except Exception:
        return None
    if (parts.scheme or "").lower() != "https":
        return None
    host = (parts.hostname or "").strip()
    if not host:
        return None
    port = int(parts.port or 443)
    return host, port


def _parse_cert_not_after(cert: dict[str, Any]) -> datetime | None:
    # Python ssl.getpeercert() returns e.g. "Feb  6 12:00:00 2026 GMT"
    s = cert.get("notAfter")
    if not isinstance(s, str) or not s.strip():
        return None
    ss = s.strip()
    try:
        dt = datetime.strptime(ss, "%b %d %H:%M:%S %Y %Z")
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def _check_one_host_port(
    *,
    domain: str,
    host: str,
    port: int,
    min_days_valid: float,
    timeout_seconds: float,
) -> TlsCertCheckResult:
    ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED

    reader = writer = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host=host, port=port, ssl=ctx, server_hostname=host),
            timeout=max(1.0, float(timeout_seconds)),
        )
        sslobj = writer.get_extra_info("ssl_object")
        cert = sslobj.getpeercert() if sslobj else {}

        not_after = _parse_cert_not_after(cert) if isinstance(cert, dict) else None
        days_remaining = None
        not_after_iso = None
        if not_after is not None:
            not_after_iso = not_after.isoformat()
            days_remaining = (not_after - datetime.now(timezone.utc)).total_seconds() / 86400.0

        ok = True
        err = None
        if not_after is None:
            ok = False
            err = "missing_notAfter"
        elif days_remaining is None:
            ok = False
            err = "missing_days_remaining"
        elif float(days_remaining) < float(min_days_valid):
            ok = False
            err = f"expires_soon: days_remaining={days_remaining:.2f} < {float(min_days_valid):.2f}"

        details: dict[str, Any] = {
            "not_after": cert.get("notAfter") if isinstance(cert, dict) else None,
            "subject": cert.get("subject") if isinstance(cert, dict) else None,
            "issuer": cert.get("issuer") if isinstance(cert, dict) else None,
            "subjectAltName": cert.get("subjectAltName") if isinstance(cert, dict) else None,
        }
        return TlsCertCheckResult(
            domain=domain,
            ok=ok,
            host=host,
            port=int(port),
            not_after_iso=not_after_iso,
            days_remaining=days_remaining,
            error=err,
            details=details,
        )
    except Exception as exc:
        return TlsCertCheckResult(
            domain=domain,
            ok=False,
            host=host,
            port=int(port),
            not_after_iso=None,
            days_remaining=None,
            error=f"{type(exc).__name__}: {exc}",
            details={},
        )
    finally:
        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


async def check_tls_certs(
    *,
    urls_by_domain: dict[str, str],
    min_days_valid: float,
    timeout_seconds: float,
    concurrency: int = 20,
) -> list[TlsCertCheckResult]:
    sem = asyncio.Semaphore(max(1, int(concurrency)))

    async def _run_one(domain: str, url: str) -> TlsCertCheckResult | None:
        target = _tls_host_port_from_url(url)
        if target is None:
            return None
        host, port = target
        async with sem:
            return await _check_one_host_port(
                domain=domain,
                host=host,
                port=port,
                min_days_valid=float(min_days_valid),
                timeout_seconds=float(timeout_seconds),
            )

    tasks = [asyncio.create_task(_run_one(d, u)) for d, u in urls_by_domain.items()]
    out: list[TlsCertCheckResult] = []
    for fut in asyncio.as_completed(tasks):
        r = await fut
        if r is not None:
            out.append(r)
    out.sort(key=lambda x: x.domain)
    return out
