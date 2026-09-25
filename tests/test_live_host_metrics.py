# Copyright (c) 2026 PitchAI. All rights reserved.
"""Live sample-history, container, and host-log checks."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

from domain_checks.common_check import DomainCheckSpec
from domain_checks.history import SampleHistory, append_sample
from domain_checks.main import check_one_domain
from domain_checks.metrics_container_health import check_container_health
from domain_checks.metrics_nginx import (
    compute_access_window_stats,
    parse_recent_upstream_errors,
)
from domain_checks.metrics_red import compute_red_violations
from domain_checks.metrics_slo import compute_slo_burn_violations
from domain_checks.testing import verify

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from domain_checks.common_check import DomainCheckResult
    from domain_checks.types import JsonValue

pytestmark = pytest.mark.live
if os.getenv("RUN_LIVE_TESTS") != "1":
    pytest.skip(
        "Set RUN_LIVE_TESTS=1 to run live metric checks",
        allow_module_level=True,
    )


def _sample_values(result: DomainCheckResult) -> tuple[float | None, int | None]:
    """Extract optional numeric HTTP sample fields from a domain result.

    Returns:
        Optional elapsed milliseconds and status code.
    """
    elapsed_value = result.details.get("http_elapsed_ms")
    http_ms: float | None = None
    if elapsed_value is not None:
        if not isinstance(elapsed_value, (bool, int, float, str)):
            pytest.fail(f"Unexpected HTTP elapsed value: {elapsed_value!r}")
        http_ms = float(elapsed_value)

    status_value = result.details.get("status_code")
    status_code: int | None = None
    if status_value is not None:
        if not isinstance(status_value, (bool, int, float, str)):
            pytest.fail(f"Unexpected HTTP status value: {status_value!r}")
        status_code = int(status_value)
    return http_ms, status_code


@pytest.fixture(name="http_client")
async def live_http_client() -> AsyncGenerator[httpx.AsyncClient]:
    """Create an HTTP client for live checks.

    Yields:
        A configured asynchronous HTTP client.
    """
    async with httpx.AsyncClient(
        headers={"User-Agent": "PitchAI Service Monitoring Bot"},
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_live_slo_and_red_from_real_samples(
    http_client: httpx.AsyncClient,
) -> None:
    """Verify SLO and RED violations computed from real external samples."""
    ok_spec = DomainCheckSpec(domain="example.com", url="https://example.com")
    bad_spec = DomainCheckSpec(domain="httpstat.us", url="https://httpstat.us/500")
    semaphore = asyncio.Semaphore(1)

    history_by_domain = SampleHistory()
    now = time.time()
    for sample_index in range(5):
        for spec in (ok_spec, bad_spec):
            result = await check_one_domain(
                spec, http_client, None, browser_semaphore=semaphore,
            )
            http_ms, status_code = _sample_values(result)

            append_sample(
                history_by_domain,
                domain=spec.domain,
                ts=now + float(sample_index),
                ok=result.ok,
                http_elapsed_ms=http_ms,
                browser_elapsed_ms=None,
                status_code=status_code,
            )

    burn_rate_rules: list[JsonValue] = [
        {
            "name": "live_test_burn",
            "short_window_minutes": 60,
            "long_window_minutes": 60,
            "short_burn_rate": 1.0,
            "long_burn_rate": 1.0,
        },
    ]
    violations = compute_slo_burn_violations(
        history_by_domain=history_by_domain,
        now_ts=time.time(),
        slo_target_percent=99.0,
        burn_rate_rules=burn_rate_rules,
        min_total_samples=3,
    )
    violation_domains = {violation.domain for violation in violations}
    verify(
        "httpstat.us" in violation_domains,
        f"Expected SLO violation: {violations!r}",
    )

    violations = compute_red_violations(
        history_by_domain=history_by_domain,
        now_ts=time.time(),
        window_minutes=60,
        min_samples=3,
        error_rate_max_percent=5.0,
        http_p95_ms_max=None,
        browser_p95_ms_max=None,
    )
    violation_domains = {violation.domain for violation in violations}
    verify(
        "httpstat.us" in violation_domains,
        f"Expected RED violation: {violations!r}",
    )


@pytest.mark.asyncio
async def test_live_container_health_if_available() -> None:
    """Verify container-health parsing against a mounted Docker socket."""
    docker_socket = Path("/var/run/docker.sock")
    if not await asyncio.to_thread(docker_socket.exists):
        pytest.skip(
            "No /var/run/docker.sock mounted; skipping container health live test",
        )

    issues, _restart_counts = await check_container_health(
        docker_socket_path=str(docker_socket),
        include_name_patterns=[],
        exclude_name_patterns=[],
        monitor_all=True,
        previous_restart_counts={},
        timeout_seconds=3.0,
    )
    issue_names = [issue.name for issue in issues]
    verify(all(issue_names))


def test_live_nginx_logs_if_available() -> None:
    """Verify nginx log parsers against mounted live logs when available."""
    access_log = Path("/var/log/nginx/access.log")
    error_log = Path("/var/log/nginx/error.log")
    if not access_log.exists() and not error_log.exists():
        pytest.skip("No /var/log/nginx mounted; skipping nginx live test")

    now = datetime.now(UTC)
    if access_log.exists():
        stats = compute_access_window_stats(
            access_log_path=str(access_log),
            now=now,
            window_seconds=300,
            max_bytes=1_000_000,
        )
        verify(stats is None or stats.total >= 0)

    if error_log.exists():
        events = parse_recent_upstream_errors(
            error_log_path=str(error_log),
            now=now,
            window_seconds=300,
            local_tz=UTC,
            max_bytes=1_000_000,
        )
        event_messages = [event.message for event in events]
        verify(all(event_messages))
