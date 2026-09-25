# Copyright (c) 2026 PitchAI. All rights reserved.
"""Live TLS, DNS, API-contract, and proxy checks."""

from __future__ import annotations

import os
from http import HTTPStatus
from typing import TYPE_CHECKING

import httpx
import pytest

from domain_checks.common_check import DomainCheckResult, http_get_check
from domain_checks.metrics_api_contract import run_api_contract_checks
from domain_checks.metrics_dns import check_dns
from domain_checks.metrics_proxy import check_upstream_header_expectations
from domain_checks.metrics_tls import check_tls_certs
from domain_checks.testing import verify
from tests.live_metrics_support import load_enabled_specs_and_config, numeric_setting

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from domain_checks.metrics_api_contract import ApiContractCheckResult

pytestmark = pytest.mark.live
if os.getenv("RUN_LIVE_TESTS") != "1":
    pytest.skip(
        "Set RUN_LIVE_TESTS=1 to run live metric checks",
        allow_module_level=True,
    )


@pytest.fixture(name="http_client")
async def live_http_client() -> AsyncGenerator[httpx.AsyncClient]:
    """Create an HTTP client for live checks.

    Yields:
        A configured asynchronous HTTP client.
    """
    async with httpx.AsyncClient(headers={"User-Agent": "PitchAI Service Monitoring Bot"}) as client:
        yield client


@pytest.mark.asyncio
async def test_live_tls_enabled_domains_ok() -> None:
    """Verify TLS certificates for all enabled domains."""
    config, enabled_specs = load_enabled_specs_and_config()
    tls_cfg = config.get("tls")
    if not isinstance(tls_cfg, dict):
        pytest.fail("Expected TLS config mapping")

    results = await check_tls_certs(
        urls_by_domain={spec.domain: spec.url for spec in enabled_specs},
        min_days_valid=numeric_setting(tls_cfg, "min_days_valid", 14.0),
        timeout_seconds=numeric_setting(tls_cfg, "timeout_seconds", 8.0),
    )
    failures = [result for result in results if not result.ok]
    verify(not failures, f"TLS failures: {failures!r}")


@pytest.mark.asyncio
async def test_live_tls_failure_expired_badssl() -> None:
    """Verify an expired public certificate produces a TLS failure."""
    results = await check_tls_certs(
        urls_by_domain={"expired.badssl.com": "https://expired.badssl.com"},
        min_days_valid=14.0,
        timeout_seconds=8.0,
    )
    verify(results)
    verify(results[0].ok is False)
    verify(results[0].error, "Expected TLS error for expired.badssl.com")


@pytest.mark.asyncio
async def test_live_dns_enabled_domains_ok() -> None:
    """Verify DNS records for all enabled domains."""
    config, enabled_specs = load_enabled_specs_and_config()
    dns_cfg = config.get("dns")
    if not isinstance(dns_cfg, dict):
        pytest.fail("Expected DNS config mapping")

    raw_resolvers = dns_cfg.get("resolvers")
    resolvers: list[str] | None
    if raw_resolvers is None:
        resolvers = None
    elif isinstance(raw_resolvers, list):
        resolvers = []
        for resolver in raw_resolvers:
            if not isinstance(resolver, str):
                pytest.fail(f"Expected DNS resolver string, got {resolver!r}")
            cleaned = resolver.strip()
            if cleaned:
                resolvers.append(cleaned)
    else:
        pytest.fail(f"Expected DNS resolvers list, got {raw_resolvers!r}")

    results = await check_dns(
        domains=[spec.domain for spec in enabled_specs],
        resolvers=resolvers,
        timeout_seconds=numeric_setting(dns_cfg, "timeout_seconds", 4.0),
        require_ipv4=bool(dns_cfg.get("require_ipv4", True)),
        require_ipv6=bool(dns_cfg.get("require_ipv6", False)),
        previous_ips_by_domain=None,
        expected_ips_by_domain=None,
        alert_on_drift_by_domain=None,
    )
    failures = [result for result in results if not result.ok]
    verify(not failures, f"DNS failures: {failures!r}")
    ok_results = [result for result in results if result.ok]
    ok_with_error = [result for result in ok_results if result.error]
    verify(not ok_with_error, f"DNS OK results had error set: {ok_with_error!r}")


@pytest.mark.asyncio
async def test_live_dns_failure_nxdomain() -> None:
    """Verify a reserved invalid domain produces a DNS failure."""
    results = await check_dns(
        domains=["no-such-name.invalid"],
        resolvers=["1.1.1.1", "8.8.8.8"],
        timeout_seconds=3.0,
        require_ipv4=True,
        require_ipv6=False,
    )
    verify(results)
    verify(results[0].ok is False)
    verify(results[0].error, "Expected DNS error for NXDOMAIN")


@pytest.mark.asyncio
async def test_live_api_contract_checks_ok(http_client: httpx.AsyncClient) -> None:
    """Verify configured API contracts for enabled domains."""
    _config, enabled_specs = load_enabled_specs_and_config()
    specs = [spec for spec in enabled_specs if spec.api_contract_checks]
    verify(specs, "No enabled domains have api_contract_checks configured")

    failures: list[ApiContractCheckResult] = []
    for spec in specs:
        results = await run_api_contract_checks(
            http_client=http_client,
            domain=spec.domain,
            base_url=spec.url,
            checks=spec.api_contract_checks,
            timeout_seconds=10.0,
        )
        failures.extend(result for result in results if not result.ok)

    verify(not failures, f"API contract failures: {failures!r}")


@pytest.mark.asyncio
async def test_live_api_contract_failure_httpstat_500(http_client: httpx.AsyncClient) -> None:
    """Verify an unexpected live server error fails an API contract."""
    results = await run_api_contract_checks(
        http_client=http_client,
        domain="httpstat.us",
        base_url="https://httpstat.us",
        checks=[
            {
                "name": "expect_200_but_500",
                "method": "GET",
                "path": "/500",
                "expected_status_codes": [HTTPStatus.OK],
            },
        ],
        timeout_seconds=10.0,
    )
    verify(results)
    verify(results[0].ok is False)
    verify(results[0].error, "Expected an error for httpstat.us/500")


@pytest.mark.asyncio
async def test_live_proxy_upstream_header_expectations(http_client: httpx.AsyncClient) -> None:
    """Verify live responses satisfy configured proxy-header expectations."""
    _config, enabled_specs = load_enabled_specs_and_config()
    specs_by_domain = {spec.domain: spec for spec in enabled_specs}
    proxy_domains = [spec for spec in enabled_specs if spec.proxy]
    if not proxy_domains:
        pytest.skip("No enabled domains have proxy expectations configured")

    cycle_results: dict[str, DomainCheckResult] = {}
    for spec in proxy_domains:
        ok, details = await http_get_check(spec, http_client)
        cycle_results[spec.domain] = DomainCheckResult(
            domain=spec.domain,
            ok=ok,
            reason="http_only",
            details=details,
        )

        header = str(spec.proxy.get("upstream_header") or "x-aipc-upstream").strip().lower()
        captured = details.get("captured_headers")
        if not isinstance(captured, dict):
            pytest.fail(f"Missing captured headers mapping for {spec.domain}")
        verify(captured.get(header) is not None, f"Missing captured upstream header {header!r} for {spec.domain}")

    issues = check_upstream_header_expectations(
        specs_by_domain=specs_by_domain,
        cycle_results=cycle_results,
    )
    verify(not issues, f"Proxy upstream header issues: {issues!r}")
