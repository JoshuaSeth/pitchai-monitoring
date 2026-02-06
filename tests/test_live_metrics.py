from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from playwright.async_api import async_playwright

from domain_checks.common_check import DomainCheckResult, DomainCheckSpec, find_chromium_executable, http_get_check
from domain_checks.history import append_sample
from domain_checks.main import _normalize_domain_entries, check_one_domain, load_config, load_domain_spec
from domain_checks.metrics_api_contract import run_api_contract_checks
from domain_checks.metrics_container_health import check_container_health
from domain_checks.metrics_dns import check_dns
from domain_checks.metrics_nginx import compute_access_window_stats, parse_recent_upstream_errors
from domain_checks.metrics_proxy import check_upstream_header_expectations
from domain_checks.metrics_red import compute_red_violations
from domain_checks.metrics_slo import compute_slo_burn_violations
from domain_checks.metrics_synthetic import run_synthetic_transactions
from domain_checks.metrics_tls import check_tls_certs
from domain_checks.metrics_web_vitals import measure_web_vitals

pytestmark = pytest.mark.live


if os.getenv("RUN_LIVE_TESTS") != "1":
    pytest.skip("Set RUN_LIVE_TESTS=1 to run live metric checks", allow_module_level=True)


def _load_enabled_specs_and_config() -> tuple[dict, list]:
    config_path = Path(__file__).resolve().parents[1] / "domain_checks" / "config.yaml"
    config = load_config(config_path)
    raw_domains = config.get("domains") or []
    entries = _normalize_domain_entries(raw_domains if isinstance(raw_domains, list) else [])
    now_ts = time.time()
    enabled_specs = [load_domain_spec(e.raw_entry) for e in entries if not e.is_disabled(now_ts)]
    return config, enabled_specs


@pytest.fixture
async def http_client() -> httpx.AsyncClient:
    async with httpx.AsyncClient(headers={"User-Agent": "PitchAI Service Monitoring Bot"}) as client:
        yield client


@pytest.fixture
async def browser():
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")

    async with async_playwright() as p:
        b = await p.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            yield b
        finally:
            await b.close()


@pytest.mark.asyncio
async def test_live_tls_enabled_domains_ok() -> None:
    config, enabled_specs = _load_enabled_specs_and_config()
    tls_cfg = config.get("tls") if isinstance(config.get("tls"), dict) else {}
    min_days_valid = float(tls_cfg.get("min_days_valid", 14))
    timeout_seconds = float(tls_cfg.get("timeout_seconds", 8))

    urls_by_domain = {s.domain: s.url for s in enabled_specs}
    results = await check_tls_certs(
        urls_by_domain=urls_by_domain,
        min_days_valid=min_days_valid,
        timeout_seconds=timeout_seconds,
    )
    bad = [r for r in results if not r.ok]
    assert not bad, f"TLS failures: {bad!r}"


@pytest.mark.asyncio
async def test_live_tls_failure_expired_badssl() -> None:
    results = await check_tls_certs(
        urls_by_domain={"expired.badssl.com": "https://expired.badssl.com"},
        min_days_valid=14.0,
        timeout_seconds=8.0,
    )
    assert results and results[0].ok is False
    assert results[0].error, "Expected TLS error for expired.badssl.com"


@pytest.mark.asyncio
async def test_live_dns_enabled_domains_ok() -> None:
    config, enabled_specs = _load_enabled_specs_and_config()
    dns_cfg = config.get("dns") if isinstance(config.get("dns"), dict) else {}
    resolvers = dns_cfg.get("resolvers")
    resolvers = [str(x).strip() for x in resolvers] if isinstance(resolvers, list) else None
    timeout_seconds = float(dns_cfg.get("timeout_seconds", 4))
    require_ipv4 = bool(dns_cfg.get("require_ipv4", True))
    require_ipv6 = bool(dns_cfg.get("require_ipv6", False))

    results = await check_dns(
        domains=[s.domain for s in enabled_specs],
        resolvers=resolvers,
        timeout_seconds=timeout_seconds,
        require_ipv4=require_ipv4,
        require_ipv6=require_ipv6,
        previous_ips_by_domain=None,
        expected_ips_by_domain=None,
        alert_on_drift_by_domain=None,
    )
    bad = [r for r in results if not r.ok]
    assert not bad, f"DNS failures: {bad!r}"

    # If it's OK, don't surface spurious errors (e.g. AAAA NoAnswer when IPv6 isn't required).
    ok_with_error = [r for r in results if r.ok and r.error]
    assert not ok_with_error, f"DNS OK results had error set: {ok_with_error!r}"


@pytest.mark.asyncio
async def test_live_dns_failure_nxdomain() -> None:
    results = await check_dns(
        domains=["no-such-name.invalid"],
        resolvers=["1.1.1.1", "8.8.8.8"],
        timeout_seconds=3.0,
        require_ipv4=True,
        require_ipv6=False,
    )
    assert results and results[0].ok is False
    assert results[0].error, "Expected DNS error for NXDOMAIN"


@pytest.mark.asyncio
async def test_live_api_contract_checks_ok(http_client: httpx.AsyncClient) -> None:
    _config, enabled_specs = _load_enabled_specs_and_config()
    specs = [s for s in enabled_specs if s.api_contract_checks]
    assert specs, "No enabled domains have api_contract_checks configured"

    failures = []
    for spec in specs:
        results = await run_api_contract_checks(
            http_client=http_client,
            domain=spec.domain,
            base_url=spec.url,
            checks=spec.api_contract_checks,
            timeout_seconds=10.0,
        )
        failures.extend([r for r in results if not r.ok])

    assert not failures, f"API contract failures: {failures!r}"


@pytest.mark.asyncio
async def test_live_api_contract_failure_httpstat_500(http_client: httpx.AsyncClient) -> None:
    results = await run_api_contract_checks(
        http_client=http_client,
        domain="httpstat.us",
        base_url="https://httpstat.us",
        checks=[{"name": "expect_200_but_500", "method": "GET", "path": "/500", "expected_status_codes": [200]}],
        timeout_seconds=10.0,
    )
    assert results and results[0].ok is False
    # Real "failure mode" test: httpstat.us can respond with 500 or disconnect; both are valid failures.
    assert results[0].error, "Expected an error for httpstat.us/500"


@pytest.mark.asyncio
async def test_live_proxy_upstream_header_expectations(http_client: httpx.AsyncClient) -> None:
    _config, enabled_specs = _load_enabled_specs_and_config()
    specs_by_domain = {s.domain: s for s in enabled_specs}

    # Only validate domains that explicitly configured proxy expectations.
    proxy_domains = [s for s in enabled_specs if isinstance(getattr(s, "proxy", None), dict) and s.proxy]
    if not proxy_domains:
        pytest.skip("No enabled domains have proxy expectations configured")

    cycle_results = {}
    for spec in proxy_domains:
        # Use HTTP-only for stability; proxy headers are captured in the HTTP response.
        ok, details = await http_get_check(spec, http_client)
        cycle_results[spec.domain] = DomainCheckResult(
            domain=spec.domain,
            ok=ok,
            reason="http_only",
            details=details,
        )

        header = str((spec.proxy or {}).get("upstream_header") or "x-aipc-upstream").strip().lower()
        captured = (details or {}).get("captured_headers")
        captured = captured if isinstance(captured, dict) else {}
        assert captured.get(header) is not None, f"Missing captured upstream header {header!r} for {spec.domain}"

    issues = check_upstream_header_expectations(specs_by_domain=specs_by_domain, cycle_results=cycle_results)
    assert not issues, f"Proxy upstream header issues: {issues!r}"


@pytest.mark.asyncio
async def test_live_synthetic_transactions_ok(browser) -> None:
    _config, enabled_specs = _load_enabled_specs_and_config()
    specs = [s for s in enabled_specs if s.synthetic_transactions]
    assert specs, "No enabled domains have synthetic_transactions configured"

    failures = []
    # Keep this serialized to reduce pressure on the host + target services.
    for spec in specs:
        results = await run_synthetic_transactions(
            domain=spec.domain,
            base_url=spec.url,
            browser=browser,
            transactions=spec.synthetic_transactions,
            timeout_seconds=45.0,
        )
        failures.extend([r for r in results if not r.ok and not r.browser_infra_error])

    assert not failures, f"Synthetic transaction failures: {failures!r}"


@pytest.mark.asyncio
async def test_live_synthetic_transactions_failure_invalid_domain(browser) -> None:
    results = await run_synthetic_transactions(
        domain="no-such-name.invalid",
        base_url="https://no-such-name.invalid",
        browser=browser,
        transactions=[{"name": "goto_should_fail", "steps": [{"type": "goto"}]}],
        timeout_seconds=12.0,
    )
    assert results and results[0].ok is False
    assert results[0].browser_infra_error is False


@pytest.mark.asyncio
async def test_live_web_vitals_ok(browser) -> None:
    _config, enabled_specs = _load_enabled_specs_and_config()
    # Pick a stable, representative app (first enabled spec).
    spec = enabled_specs[0]
    r = await measure_web_vitals(
        domain=spec.domain,
        url=spec.url,
        browser=browser,
        timeout_seconds=60.0,
        post_load_wait_ms=4500,
    )
    assert r.ok is True, f"Web vitals failed: {r!r}"
    assert isinstance(r.metrics, dict)
    assert "lcp_ms" in r.metrics and "cls" in r.metrics and "inp_ms" in r.metrics


@pytest.mark.asyncio
async def test_live_web_vitals_failure_invalid_domain(browser) -> None:
    r = await measure_web_vitals(
        domain="no-such-name.invalid",
        url="https://no-such-name.invalid",
        browser=browser,
        timeout_seconds=12.0,
        post_load_wait_ms=1000,
    )
    assert r.ok is False
    assert r.browser_infra_error is False


@pytest.mark.asyncio
async def test_live_slo_and_red_from_real_samples(http_client: httpx.AsyncClient) -> None:
    # Build a short, real sample history by hitting real external endpoints
    # (no mocks, no local servers).
    ok_spec = DomainCheckSpec(domain="example.com", url="https://example.com")
    bad_spec = DomainCheckSpec(domain="httpstat.us", url="https://httpstat.us/500")
    sem = asyncio.Semaphore(1)

    history_by_domain = {}
    now = time.time()
    for i in range(5):
        for spec in (ok_spec, bad_spec):
            result = await check_one_domain(spec, http_client, None, browser_semaphore=sem)
            details = result.details or {}
            http_ms = None
            try:
                if details.get("http_elapsed_ms") is not None:
                    http_ms = float(details.get("http_elapsed_ms"))
            except Exception:
                http_ms = None
            status_code = None
            try:
                if details.get("status_code") is not None:
                    status_code = int(details.get("status_code"))
            except Exception:
                status_code = None

            append_sample(
                history_by_domain,
                domain=spec.domain,
                ts=now + float(i),
                ok=bool(result.ok),
                http_elapsed_ms=http_ms,
                browser_elapsed_ms=None,
                status_code=status_code,
            )

    slo_violations = compute_slo_burn_violations(
        history_by_domain=history_by_domain,
        now_ts=time.time(),
        slo_target_percent=99.0,
        burn_rate_rules=[
            {
                "name": "live_test_burn",
                "short_window_minutes": 60,
                "long_window_minutes": 60,
                "short_burn_rate": 1.0,
                "long_burn_rate": 1.0,
            }
        ],
        min_total_samples=3,
    )
    assert any(v.domain == "httpstat.us" for v in slo_violations), f"Expected SLO violation: {slo_violations!r}"

    red_violations = compute_red_violations(
        history_by_domain=history_by_domain,
        now_ts=time.time(),
        window_minutes=60,
        min_samples=3,
        error_rate_max_percent=5.0,
        http_p95_ms_max=None,
        browser_p95_ms_max=None,
    )
    assert any(v.domain == "httpstat.us" for v in red_violations), f"Expected RED violation: {red_violations!r}"


@pytest.mark.asyncio
async def test_live_container_health_if_available() -> None:
    docker_sock = Path("/var/run/docker.sock")
    if not docker_sock.exists():
        pytest.skip("No /var/run/docker.sock mounted; skipping container health live test")

    issues, _restart_counts = await check_container_health(
        docker_socket_path=str(docker_sock),
        include_name_patterns=[],
        exclude_name_patterns=[],
        monitor_all=True,
        previous_restart_counts={},
        timeout_seconds=3.0,
    )
    assert isinstance(issues, list)


@pytest.mark.asyncio
async def test_live_nginx_logs_if_available() -> None:
    access = Path("/var/log/nginx/access.log")
    error = Path("/var/log/nginx/error.log")
    if not access.exists() and not error.exists():
        pytest.skip("No /var/log/nginx mounted; skipping nginx live test")

    now = datetime.now(timezone.utc)
    if access.exists():
        stats = compute_access_window_stats(
            access_log_path=str(access),
            now=now,
            window_seconds=300,
            max_bytes=1_000_000,
        )
        # Just validate parser stability against the real log; content varies.
        assert stats is None or stats.total >= 0

    if error.exists():
        events = parse_recent_upstream_errors(
            error_log_path=str(error),
            now=now,
            window_seconds=300,
            local_tz=timezone.utc,
            max_bytes=1_000_000,
        )
        assert isinstance(events, list)
