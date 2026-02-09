from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from domain_checks.common_check import DomainCheckResult, DomainCheckSpec
from domain_checks.docker_unix import DockerUnixResponse
from domain_checks.metrics_container_health import check_container_health
from domain_checks.metrics_dns import check_dns
from domain_checks.metrics_nginx import compute_access_window_stats, parse_recent_upstream_errors, summarize_upstream_errors
from domain_checks.metrics_proxy import check_upstream_header_expectations
from domain_checks.metrics_tls import _parse_cert_not_after, _tls_host_port_from_url


@pytest.mark.asyncio
async def test_dns_check_expected_and_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_dns_query_sync(*, domain: str, record_type: str, resolvers, timeout_seconds: float):
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
    assert res and res[0].domain == "a.example"
    # Drift is detected vs previous and alert_on_drift is enabled, so ok becomes False.
    assert res[0].drift_detected is True
    assert res[0].ok is False


def test_tls_helpers_parse_and_host_port() -> None:
    assert _tls_host_port_from_url("http://example.com") is None
    assert _tls_host_port_from_url("https://example.com") == ("example.com", 443)
    assert _tls_host_port_from_url("https://example.com:444") == ("example.com", 444)

    dt = _parse_cert_not_after({"notAfter": "Feb  6 12:00:00 2026 GMT"})
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.year == 2026


def test_proxy_upstream_header_backup_detected() -> None:
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
    assert issues
    assert issues[0].reason == "backup_upstream_in_use"


@pytest.mark.asyncio
async def test_container_health_detects_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_json(*, socket_path: str, path: str, timeout_seconds: float = 5.0) -> DockerUnixResponse:
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
    assert issues
    assert issues[0].name == "svc"
    assert issues[0].health_status == "unhealthy"
    assert issues[0].restart_increase == 1
    assert restart_counts == {"id1": 2}


@pytest.mark.asyncio
async def test_container_health_ignores_sticky_oomkilled_for_running_container(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Docker's State.OOMKilled can remain True after a container is up and healthy.
    We should not spam alerts if the container is otherwise OK.
    """

    def fake_get_json(*, socket_path: str, path: str, timeout_seconds: float = 5.0) -> DockerUnixResponse:
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
    assert issues == []
    assert restart_counts == {"id1": 0}


def test_nginx_access_and_error_log_parsers(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    within = now - timedelta(seconds=10)
    old = now - timedelta(seconds=600)

    def fmt(dt: datetime) -> str:
        return dt.strftime("%d/%b/%Y:%H:%M:%S %z")

    access = tmp_path / "access.log"
    access.write_text(
        "\n".join(
            [
                f'1.1.1.1 - - [{fmt(old)}] "GET /old HTTP/1.1" 502 1 "-" "ua"',
                f'1.1.1.1 - - [{fmt(within)}] "GET / HTTP/1.1" 502 1 "-" "ua"',
                f'1.1.1.1 - - [{fmt(within)}] "GET /ok HTTP/1.1" 200 1 "-" "ua"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    stats = compute_access_window_stats(access_log_path=str(access), now=now, window_seconds=120, max_bytes=50_000)
    assert stats is not None
    assert stats.total == 2
    assert stats.status_502_504 == 1
    assert stats.status_5xx == 1

    err = tmp_path / "error.log"
    err_ts = now.astimezone(timezone.utc).strftime("%Y/%m/%d %H:%M:%S")
    err.write_text(
        "\n".join(
            [
                f'{err_ts} [error] 1#1: *1 upstream timed out (110: Connection timed out) while reading response header from upstream, client: 1.1.1.1, server: svc.example, request: "GET / HTTP/1.1", upstream: "http://127.0.0.1:9999/", host: "svc.example"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    events = parse_recent_upstream_errors(
        error_log_path=str(err),
        now=now,
        window_seconds=120,
        local_tz=timezone.utc,
        max_bytes=50_000,
    )
    assert events and events[0].server == "svc.example"
    summary = summarize_upstream_errors(events)
    assert summary["counts_by_server"]["svc.example"] == 1
