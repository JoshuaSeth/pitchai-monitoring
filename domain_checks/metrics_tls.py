# Copyright (c) 2026 PitchAI. All rights reserved.
"""PitchAI domain monitoring support for metrics tls."""

from __future__ import annotations

import asyncio
import socket
import ssl
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NamedTuple, cast
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Mapping

    from domain_checks.types import JsonObject


type CertificateField = str | tuple[str, ...] | tuple[tuple[str, str], ...] | tuple[tuple[tuple[str, str], ...], ...]
type Certificate = dict[str, CertificateField]

_SECONDS_PER_DAY = 86_400.0


class TlsCertCheckResult(NamedTuple):
    """Represent one TLS certificate check outcome."""

    domain: str
    ok: bool
    host: str | None
    port: int | None
    not_after_iso: str | None
    days_remaining: float | None
    error: str | None
    details: JsonObject


def tls_host_port_from_url(url: str) -> tuple[str, int] | None:
    """Resolve the TLS host and port for an HTTPS URL.

    Returns:
        The host and port, or ``None`` when the URL is not a valid HTTPS URL.
    """
    try:
        parts = urlsplit(str(url or "").strip())
    except ValueError:
        return None
    try:
        port = int(parts.port or 443)
    except ValueError:
        return None
    if (parts.scheme or "").lower() != "https":
        return None
    host = (parts.hostname or "").strip()
    if not host:
        return None
    return host, port


def parse_cert_not_after(cert: Mapping[str, CertificateField]) -> datetime | None:
    """Parse an OpenSSL certificate expiration timestamp.

    Returns:
        The UTC expiration timestamp, or ``None`` when it cannot be parsed.
    """
    # Python ssl.getpeercert() returns e.g. "Feb  6 12:00:00 2026 GMT"
    s = cert.get("notAfter")
    if not isinstance(s, str) or not s.strip():
        return None
    ss = s.strip()
    try:
        dt = datetime.strptime(ss, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
    except ValueError:
        return None
    return dt.astimezone(UTC)


def _certificate_detail(cert: Certificate, key: str) -> str | None:
    value = cert.get(key)
    if value is None:
        return None
    return value if isinstance(value, str) else repr(value)


def _fetch_certificate(*, host: str, port: int, timeout_seconds: float) -> Certificate:
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    with (
        socket.create_connection((host, port), timeout=timeout_seconds) as raw_socket,
        context.wrap_socket(raw_socket, server_hostname=host) as secure_socket,
    ):
        return cast("Certificate", secure_socket.getpeercert())


def _certificate_result(
    *,
    domain: str,
    host: str,
    port: int,
    min_days_valid: float,
    cert: Certificate,
) -> TlsCertCheckResult:
    not_after = parse_cert_not_after(cert)
    days_remaining = (
        (not_after - datetime.now(UTC)).total_seconds() / _SECONDS_PER_DAY if not_after is not None else None
    )
    error = None
    if not_after is None:
        error = "missing_notAfter"
    elif days_remaining is None:
        error = "missing_days_remaining"
    elif days_remaining < min_days_valid:
        error = f"expires_soon: days_remaining={days_remaining:.2f} < {min_days_valid:.2f}"
    details: JsonObject = {
        "not_after": _certificate_detail(cert, "notAfter"),
        "subject": _certificate_detail(cert, "subject"),
        "issuer": _certificate_detail(cert, "issuer"),
        "subjectAltName": _certificate_detail(cert, "subjectAltName"),
    }
    return TlsCertCheckResult(
        domain=domain,
        ok=error is None,
        host=host,
        port=port,
        not_after_iso=not_after.isoformat() if not_after is not None else None,
        days_remaining=days_remaining,
        error=error,
        details=details,
    )


async def _check_one_host_port(
    *,
    domain: str,
    host: str,
    port: int,
    min_days_valid: float,
    timeout_seconds: float,
) -> TlsCertCheckResult:
    try:
        cert = await asyncio.to_thread(
            _fetch_certificate,
            host=host,
            port=port,
            timeout_seconds=max(1.0, float(timeout_seconds)),
        )
    except (OSError, ValueError) as exc:
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
    return _certificate_result(
        domain=domain,
        host=host,
        port=port,
        min_days_valid=float(min_days_valid),
        cert=cert,
    )


async def check_tls_certs(
    *,
    urls_by_domain: dict[str, str],
    min_days_valid: float,
    timeout_seconds: float,
    concurrency: int = 20,
) -> list[TlsCertCheckResult]:
    """Check TLS certificate validity for configured HTTPS domains.

    Returns:
        Certificate outcomes ordered by domain.
    """
    sem = asyncio.Semaphore(max(1, int(concurrency)))

    async def _run_one(domain: str, url: str) -> TlsCertCheckResult | None:
        target = tls_host_port_from_url(url)
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

    domain_urls = urls_by_domain.items()
    tasks = [asyncio.create_task(_run_one(d, u)) for d, u in domain_urls]
    out: list[TlsCertCheckResult] = []
    for fut in asyncio.as_completed(tasks):
        r = await fut
        if r is not None:
            out.append(r)
    out.sort(key=lambda x: x.domain)
    return out
