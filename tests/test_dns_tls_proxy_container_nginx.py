# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tests for test dns tls proxy container nginx behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from domain_checks.common_check import DomainCheckResult, DomainCheckSpec
from domain_checks.docker_unix import DockerUnixResponse
from domain_checks.metrics_container_health import check_container_health
from domain_checks.metrics_dns import check_dns
from domain_checks.metrics_nginx import (
    compute_access_window_stats,
    parse_recent_upstream_errors,
    summarize_upstream_errors,
)
from domain_checks.metrics_proxy import check_upstream_header_expectations
from domain_checks.metrics_tls import parse_cert_not_after, tls_host_port_from_url
from domain_checks.testing import verify

if TYPE_CHECKING:
    from pathlib import Path

_CERTIFICATE_YEAR = 2026
_EXPECTED_ACCESS_LOG_ENTRIES = 2


@pytest.mark.asyncio
async def test_dns_check_expected_and_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify dns check expected and drift."""

    def fake_dns_query_sync(
        *,
        domain: str,
        record_type: str,
        resolvers: list[str] | None,
        timeout_seconds: float,
    ) -> list[str]:
        _ = resolvers, timeout_seconds
        if domain == "a.example" and record_type == "A":
            return ["1.2.3.4"]
        if domain == "a.example" and record_type == "AAAA":
            return []
        return []

    monkeypatch.setattr("domain_checks.metrics_dns._dns_query_sync", fake_dns_query_sync)

    res = await check_dns(
        domains=["a.example"],
        resolvers=None,
        timeout_seconds=1.0,
        require_ipv4=True,
        require_ipv6=False,
        previous_ips_by_domain={"a.example": ["9.9.9.9"]},
        expected_ips_by_domain={"a.example": ["1.2.3.4"]},
        alert_on_drift_by_domain={"a.example": True},
    )
    verify(res)
    verify(res[0].domain == "a.example")
    # Drift is detected vs previous and alert_on_drift is enabled, so ok becomes False.
    verify(res[0].drift_detected is True)
    verify(res[0].ok is False)


def test_tls_helpers_parse_and_host_port() -> None:
    """Verify tls helpers parse and host port."""
    verify(tls_host_port_from_url("http://example.com") is None)
    verify(tls_host_port_from_url("https://example.com") == ("example.com", 443))
    verify(tls_host_port_from_url("https://example.com:444") == ("example.com", 444))

    dt = parse_cert_not_after({"notAfter": "Feb  6 12:00:00 2026 GMT"})
    if dt is None:
        pytest.fail("Expected certificate expiration timestamp")
    verify(dt.tzinfo is not None)
    verify(dt.year == _CERTIFICATE_YEAR)


def test_proxy_upstream_header_backup_detected() -> None:
    """Verify proxy upstream header backup detected."""
    spec = DomainCheckSpec(
        domain="svc",
        url="https://svc",
        proxy={
            "upstream_header": "x-aipc-upstream",
            "primary_upstreams": ["127.0.0.1:3120"],
            "backup_upstreams": ["127.0.0.1:3121"],
            "alert_on_backup": True,
        },
    )
    specs = {"svc": spec}
    result = DomainCheckResult(
        domain="svc",
        ok=True,
        reason="ok",
        details={"captured_headers": {"x-aipc-upstream": "127.0.0.1:3121"}},
    )
    issues = check_upstream_header_expectations(specs_by_domain=specs, cycle_results={"svc": result})
    verify(issues)
    verify(issues[0].reason == "backup_upstream_in_use")


@pytest.mark.asyncio
async def test_container_health_detects_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify container health detects unhealthy."""

    def fake_get_json(*, socket_path: str, path: str, timeout_seconds: float = 5.0) -> DockerUnixResponse:
        _ = socket_path, timeout_seconds
        if path.startswith("/containers/json"):
            return DockerUnixResponse(
                status=200,
                ok=True,
                data=[{"Id": "id1", "Names": ["/svc"], "Status": "Up 1m"}],
                error=None,
            )
        if path == "/containers/id1/json":
            return DockerUnixResponse(
                status=200,
                ok=True,
                data={
                    "State": {"Running": True, "OOMKilled": False, "ExitCode": 0, "Health": {"Status": "unhealthy"}},
                    "RestartCount": 2,
                },
                error=None,
            )
        return DockerUnixResponse(status=404, ok=False, data=None, error="not_found")

    monkeypatch.setattr("domain_checks.metrics_container_health.docker_unix_get_json", fake_get_json)

    issues, restart_counts = await check_container_health(
        docker_socket_path="/var/run/docker.sock",
        include_name_patterns=["^svc$"],
        exclude_name_patterns=[],
        monitor_all=False,
        previous_restart_counts={"id1": 1},
        timeout_seconds=1.0,
    )
    verify(issues)
    verify(issues[0].name == "svc")
    verify(issues[0].health_status == "unhealthy")
    verify(issues[0].restart_increase == 1)
    verify(restart_counts == {"id1": 2})


@pytest.mark.asyncio
async def test_container_health_ignores_sticky_oomkilled_for_running_container(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a historical OOM kill does not mark a healthy container unhealthy.

    Docker's State.OOMKilled can remain True after a container is up and healthy.
    We should not spam alerts if the container is otherwise OK.
    """

    def fake_get_json(*, socket_path: str, path: str, timeout_seconds: float = 5.0) -> DockerUnixResponse:
        _ = socket_path, timeout_seconds
        if path.startswith("/containers/json"):
            return DockerUnixResponse(
                status=200,
                ok=True,
                data=[{"Id": "id1", "Names": ["/svc"], "Status": "Up 1d (healthy)"}],
                error=None,
            )
        if path == "/containers/id1/json":
            return DockerUnixResponse(
                status=200,
                ok=True,
                data={
                    "State": {"Running": True, "OOMKilled": True, "ExitCode": 0, "Health": {"Status": "healthy"}},
                    "RestartCount": 0,
                },
                error=None,
            )
        return DockerUnixResponse(status=404, ok=False, data=None, error="not_found")

    monkeypatch.setattr("domain_checks.metrics_container_health.docker_unix_get_json", fake_get_json)

    issues, restart_counts = await check_container_health(
        docker_socket_path="/var/run/docker.sock",
        include_name_patterns=["^svc$"],
        exclude_name_patterns=[],
        monitor_all=False,
        previous_restart_counts={"id1": 0},
        timeout_seconds=1.0,
    )
    verify(issues == [])
    verify(restart_counts == {"id1": 0})


def test_nginx_access_and_error_log_parsers(tmp_path: Path) -> None:
    """Verify nginx access and error log parsers."""
    now = datetime.now(UTC)
    within = now - timedelta(seconds=10)
    old = now - timedelta(seconds=600)

    def fmt(dt: datetime) -> str:
        return dt.strftime("%d/%b/%Y:%H:%M:%S %z")

    access = tmp_path / "access.log"
    _ = access.write_text(
        "\n".join(
            [
                f'1.1.1.1 - - [{fmt(old)}] "GET /old HTTP/1.1" 502 1 "-" "ua"',
                f'1.1.1.1 - - [{fmt(within)}] "GET / HTTP/1.1" 502 1 "-" "ua"',
                f'1.1.1.1 - - [{fmt(within)}] "GET /ok HTTP/1.1" 200 1 "-" "ua"',
            ],
        )
        + "\n",
        encoding="utf-8",
    )

    stats = compute_access_window_stats(access_log_path=str(access), now=now, window_seconds=120, max_bytes=50_000)
    if stats is None:
        pytest.fail("Expected access-window statistics")
    verify(stats.total == _EXPECTED_ACCESS_LOG_ENTRIES)
    verify(stats.status_502_504 == 1)
    verify(stats.status_5xx == 1)

    err = tmp_path / "error.log"
    err_ts = now.astimezone(UTC).strftime("%Y/%m/%d %H:%M:%S")
    error_line = (
        f"{err_ts} [error] 1#1: *1 upstream timed out (110: Connection timed out) "
        "while reading response header from upstream, client: 1.1.1.1, "
        'server: svc.example, request: "GET / HTTP/1.1", '
        'upstream: "http://127.0.0.1:9999/", host: "svc.example"'
    )
    _ = err.write_text(
        f"{error_line}\n",
        encoding="utf-8",
    )
    events = parse_recent_upstream_errors(
        error_log_path=str(err),
        now=now,
        window_seconds=120,
        local_tz=UTC,
        max_bytes=50_000,
    )
    verify(events)
    verify(events[0].server == "svc.example")
    summary = summarize_upstream_errors(events)
    verify(summary["counts_by_server"]["svc.example"] == 1)
