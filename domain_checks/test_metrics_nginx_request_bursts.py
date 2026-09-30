# Copyright (c) 2026 PitchAI. All rights reserved.
"""Regress request-level counting for nginx upstream-error bursts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .metrics_nginx import (
    NginxUpstreamErrorEvent,
    compute_access_window_stats,
    parse_recent_upstream_errors,
    summarize_upstream_errors,
)

_INCIDENT_TIMESTAMP = "2026/09/19 01:21:09"
_INCIDENT_NOW = datetime(2026, 9, 19, 1, 22, tzinfo=UTC)
_INCIDENT_THRESHOLD = 5


def _upstream_error_line(
    *,
    timestamp: str = _INCIDENT_TIMESTAMP,
    worker_connection: tuple[str, str] = ("319573#319573", "1042445"),
    server: str = "deplanbook.com",
    host: str | None = None,
    request: str = "GET /static/play.js HTTP/1.1",
) -> str:
    """Build one representative nginx upstream error line.

    Returns:
        A complete nginx error-log line.
    """
    request_host = host or server
    worker, connection = worker_connection
    return (
        f"{timestamp} [error] {worker}: *{connection} upstream prematurely "
        "closed connection while reading response header from upstream, "
        f'client: 203.0.113.10, server: {server}, request: "{request}", '
        'upstream: "http://127.0.0.1:13140/static/play.js", '
        f'host: "{request_host}"'
    )


def _parse_lines(log_path: Path, lines: list[str]) -> list[NginxUpstreamErrorEvent]:
    """Write and parse one bounded error-log fixture.

    Returns:
        Parsed raw upstream events.
    """
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return parse_recent_upstream_errors(
        error_log_path=str(log_path),
        now=_INCIDENT_NOW,
        window_seconds=300,
        local_tz=UTC,
        max_bytes=50_000,
    )


def test_identical_incident_lines_count_as_one_request(tmp_path: Path) -> None:
    """Collapse the five-line Sep 19 burst without hiding its raw evidence.

    Raises:
        AssertionError: When raw or request-level incident evidence changes.
    """
    incident_line = _upstream_error_line()
    events = _parse_lines(tmp_path / "error.log", [incident_line] * 5)

    summary = summarize_upstream_errors(events)
    first_identity = events[0].identity
    observed = {
        "raw_line_count": len(events),
        "connection_id": first_identity.connection_id,
        "request": first_identity.request,
        "host": first_identity.host,
        "request_counts": summary["counts_by_server"],
        "raw_counts": summary["raw_counts_by_server"],
        "duplicate_counts": summary["duplicate_counts_by_server"],
        "request_event_count": summary["request_event_count"],
        "raw_event_count": summary["raw_event_count"],
        "samples": summary["samples_by_server"]["deplanbook.com"],
    }
    expected = {
        "raw_line_count": _INCIDENT_THRESHOLD,
        "connection_id": "319573#319573:*1042445",
        "request": "GET /static/play.js HTTP/1.1",
        "host": "deplanbook.com",
        "request_counts": {"deplanbook.com": 1},
        "raw_counts": {"deplanbook.com": _INCIDENT_THRESHOLD},
        "duplicate_counts": {"deplanbook.com": 4},
        "request_event_count": 1,
        "raw_event_count": _INCIDENT_THRESHOLD,
        "samples": [incident_line] * 3,
    }
    if observed != expected:
        message = f"incident evidence changed: expected {expected!r}, observed {observed!r}"
        raise AssertionError(message)
    if summary["counts_by_server"]["deplanbook.com"] >= _INCIDENT_THRESHOLD:
        message = "duplicate raw lines crossed the request-level alert threshold"
        raise AssertionError(message)


def test_reused_connections_keep_distinct_failed_requests(tmp_path: Path) -> None:
    """Do not mistake a keepalive connection for a request identifier.

    Raises:
        AssertionError: When distinct request identities are collapsed.
    """
    first = _upstream_error_line(request="GET /first HTTP/1.1")
    events = _parse_lines(
        tmp_path / "error.log",
        [
            first,
            first,
            _upstream_error_line(request="GET /second HTTP/1.1"),
            _upstream_error_line(
                timestamp="2026/09/19 01:21:10",
                request="GET /first HTTP/1.1",
            ),
            _upstream_error_line(
                worker_connection=("319573#319573", "1042446"),
                request="GET /first HTTP/1.1",
            ),
            _upstream_error_line(
                worker_connection=("319574#319574", "1042445"),
                request="GET /first HTTP/1.1",
            ),
            _upstream_error_line(
                host="alias.deplanbook.com",
                request="GET /first HTTP/1.1",
            ),
            _upstream_error_line(
                server="other.example",
                request="GET /first HTTP/1.1",
            ),
        ],
    )

    summary = summarize_upstream_errors(events)
    observed = (
        summary["counts_by_server"],
        summary["raw_counts_by_server"],
        summary["duplicate_counts_by_server"],
    )
    expected = (
        {"deplanbook.com": 6, "other.example": 1},
        {"deplanbook.com": 7, "other.example": 1},
        {"deplanbook.com": 1, "other.example": 0},
    )
    if observed != expected:
        message = f"distinct request counts changed: expected {expected!r}, observed {observed!r}"
        raise AssertionError(message)


def test_unidentified_lines_are_never_collapsed() -> None:
    """Count raw lines when request identity is incomplete or unsafe.

    Raises:
        AssertionError: When unidentified events are deduplicated.
    """
    unidentified = NginxUpstreamErrorEvent(
        ts=_INCIDENT_TIMESTAMP,
        level="error",
        server="deplanbook.com",
        upstream=None,
        message="raw upstream failure",
    )

    summary = summarize_upstream_errors([unidentified, unidentified])
    observed = (
        summary["counts_by_server"],
        summary["raw_counts_by_server"],
        summary["duplicate_counts_by_server"],
    )
    expected = (
        {"deplanbook.com": 2},
        {"deplanbook.com": 2},
        {"deplanbook.com": 0},
    )
    if observed != expected:
        message = f"unidentified event counts changed: expected {expected!r}, observed {observed!r}"
        raise AssertionError(message)


def test_access_parser_retains_genuine_5xx_and_gateway_failures(tmp_path: Path) -> None:
    """Keep independent access-log 5xx and 502/504 evidence unchanged.

    Raises:
        AssertionError: When access-log failure accounting changes.
    """
    recent_timestamp = "19/Sep/2026:01:21:59 +0000"
    old_timestamp = "19/Sep/2026:01:10:00 +0000"
    lines = [
        f'203.0.113.10 - - [{old_timestamp}] "GET /old HTTP/1.1" 502 1 "-" "ua"',
        f'203.0.113.10 - - [{recent_timestamp}] "GET /ok HTTP/1.1" 200 1 "-" "ua"',
        f'203.0.113.10 - - [{recent_timestamp}] "GET /bad HTTP/1.1" 502 1 "-" "ua"',
        f'203.0.113.10 - - [{recent_timestamp}] "GET /slow HTTP/1.1" 504 1 "-" "ua"',
        f'203.0.113.10 - - [{recent_timestamp}] "GET /down HTTP/1.1" 503 1 "-" "ua"',
        f'203.0.113.10 - - [{recent_timestamp}] "GET /missing HTTP/1.1" 404 1 "-" "ua"',
    ]
    access_log = tmp_path / "access.log"
    access_log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    stats = compute_access_window_stats(
        access_log_path=str(access_log),
        now=datetime(2026, 9, 19, 1, 22, tzinfo=UTC),
        window_seconds=300,
        max_bytes=50_000,
    )
    if stats is None:
        message = "access stats unexpectedly absent"
        raise AssertionError(message)
    observed = (
        stats.total,
        stats.status_5xx,
        stats.status_502_504,
        stats.status_4xx,
        len(stats.sample_lines),
    )
    expected = (5, 3, 2, 1, 3)
    if observed != expected:
        message = f"access failure counts changed: expected {expected!r}, observed {observed!r}"
        raise AssertionError(message)


def test_monitor_keeps_host_policy_threshold_and_raw_evidence_wiring() -> None:
    """Pin alertable-host filtering, request counts, and raw event evidence.

    Raises:
        AssertionError: When a required monitor policy contract is missing.
    """
    monitor_source = (Path(__file__).parent / "main.py").read_text(encoding="utf-8")

    host_filter = (
        "event.server not in entries_by_domain or event.server in alertable_domains"
    )
    observed = {
        "alertable_host_filter": host_filter in monitor_source,
        "request_counts_consumed": 'counts = upstream_summary.get("counts_by_server")'
        in monitor_source,
        "enabled_domain_gate": "if server not in enabled_domains:" in monitor_source,
        "threshold_gate": "if int(count) >= int(proxy_max_upstream_errors_per_domain):"
        in monitor_source,
        "raw_evidence_count": "upstream_events=int(len(upstream_events or []))"
        in monitor_source,
    }
    if not all(observed.values()):
        message = f"monitor policy contract changed: {observed!r}"
        raise AssertionError(message)
