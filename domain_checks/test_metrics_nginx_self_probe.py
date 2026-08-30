# Copyright (c) 2026 PitchAI. All rights reserved.
"""Regression coverage for scoped Nginx traffic accounting."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .metrics_nginx import SERVICE_MONITOR_USER_AGENT, compute_access_window_stats

_EXPECTED_COUNTERS = (2, 1, 1)
_STATS_ERROR = "monitor self-probes changed the customer-traffic Nginx counters"
_ALERTABLE_HOST = "customer.pitchai.net"
_STRUCTURED_PARSE_ERROR = "structured host-scoped access log was not parsed"
_STRUCTURED_COUNTER_ERROR = "structured access-log counters changed unexpectedly"
_ALERTABLE_SAMPLE_ERROR = "alertable customer error was not retained as bounded evidence"
_LOG_FIELDS_ERROR = "managed Nginx log format lost a required traffic field"
_LOG_PRIVACY_ERROR = "managed Nginx log format records unnecessary request data"
_LOG_POLICY_ERROR = "managed Nginx host exclusions diverged from production inventory scope"


def test_access_stats_exclude_service_monitor_probes(tmp_path: Path) -> None:
    """Keep synthetic probe outcomes out of the global customer-traffic SLO.

    Raises:
        AssertionError: The parser counts monitor self-probes as customer traffic.
    """
    now = datetime.now(UTC)
    timestamp = (now - timedelta(seconds=10)).strftime("%d/%b/%Y:%H:%M:%S %z")
    synthetic_error = (
        f'1.1.1.1 - - [{timestamp}] "GET /synthetic-error HTTP/1.1" 502 1 "-" "{SERVICE_MONITOR_USER_AGENT}"'
    )
    synthetic_success = (
        f'1.1.1.1 - - [{timestamp}] "GET /synthetic-ok HTTP/1.1" 200 1 "-" "{SERVICE_MONITOR_USER_AGENT}"'
    )
    customer_error = f'1.1.1.1 - - [{timestamp}] "GET /customer-error HTTP/1.1" 504 1 "-" "customer-agent"'
    customer_success = f'1.1.1.1 - - [{timestamp}] "GET /customer-ok HTTP/1.1" 200 1 "-" "customer-agent"'
    access_log = tmp_path / "access.log"
    access_log.write_text(
        f"{synthetic_error}\n{synthetic_success}\n{customer_error}\n{customer_success}\n",
        encoding="utf-8",
    )

    stats = compute_access_window_stats(
        access_log_path=str(access_log),
        now=now,
        window_seconds=120,
        max_bytes=50_000,
    )

    if stats is None:
        raise AssertionError(_STATS_ERROR)
    counters = (stats.total, stats.status_5xx, stats.status_502_504)
    if counters != _EXPECTED_COUNTERS:
        raise AssertionError(_STATS_ERROR)
    if len(stats.sample_lines) != 1 or "/customer-error" not in stats.sample_lines[0]:
        raise AssertionError(_STATS_ERROR)


def _structured_record(*, timestamp: datetime, status: int, host: str, user_agent: str) -> str:
    return json.dumps(
        {
            "timestamp": timestamp.isoformat(),
            "status": status,
            "host": host,
            "user_agent": user_agent,
        },
        separators=(",", ":"),
    )


def test_access_stats_parse_structured_records_and_exclude_monitor(tmp_path: Path) -> None:
    """Parse the host-aware format while excluding the monitor's own probes.

    Raises:
        AssertionError: Structured counters or synthetic exclusion regress.
    """
    now = datetime.now(UTC)
    timestamp = now - timedelta(seconds=10)
    records = [
        _structured_record(
            timestamp=timestamp,
            status=502,
            host=_ALERTABLE_HOST,
            user_agent=SERVICE_MONITOR_USER_AGENT,
        ),
        _structured_record(
            timestamp=timestamp,
            status=504,
            host=_ALERTABLE_HOST.upper() + ".",
            user_agent="customer-agent",
        ),
        _structured_record(
            timestamp=timestamp,
            status=200,
            host=_ALERTABLE_HOST,
            user_agent="customer-agent",
        ),
    ]
    access_log = tmp_path / "service-monitoring-access.log"
    access_log.write_text("\n".join(records) + "\n", encoding="utf-8")

    stats = compute_access_window_stats(
        access_log_path=str(access_log),
        now=now,
        window_seconds=120,
        max_bytes=50_000,
    )

    if stats is None:
        raise AssertionError(_STRUCTURED_PARSE_ERROR)
    counters = (stats.total, stats.status_5xx, stats.status_502_504)
    if counters != _EXPECTED_COUNTERS:
        raise AssertionError(_STRUCTURED_COUNTER_ERROR)
    if len(stats.sample_lines) != 1 or _ALERTABLE_HOST not in stats.sample_lines[0].lower():
        raise AssertionError(_ALERTABLE_SAMPLE_ERROR)


def test_managed_nginx_log_format_is_host_aware_and_privacy_minimized() -> None:
    """Keep the dedicated traffic signal attributable without logging request data.

    Raises:
        AssertionError: The managed format loses attribution, privacy, or routing alignment.
    """
    config_path = Path(__file__).parents[1] / "deploy/nginx/service-monitoring-access-log.conf"
    config = config_path.read_text(encoding="utf-8")
    required_variables = ("$time_iso8601", "$status", "$host", "$http_user_agent")
    forbidden_variables = ("$remote_addr", "$request", "$request_uri", "$args", "$http_referer")
    if not all(variable in config for variable in required_variables):
        raise AssertionError(_LOG_FIELDS_ERROR)
    if any(variable in config for variable in forbidden_variables):
        raise AssertionError(_LOG_PRIVACY_ERROR)
    if "if=$pitchai_service_monitoring_production" not in config:
        raise AssertionError(_LOG_POLICY_ERROR)

    inventory_text = Path(__file__).with_name("config.yaml").read_text(encoding="utf-8")
    domains_block = inventory_text.split("\ndomains:\n", 1)[1].split("\nretired_domains:\n", 1)[0]
    inventory_hosts: set[str] = set()
    for entry in ("\n" + domains_block).split("\n  - domain: ")[1:]:
        host = entry.splitlines()[0].strip()
        is_production = "\n    environment: production\n" in "\n" + entry
        is_dashboard_only = "      telegram: dashboard-only" in entry
        if not is_production or is_dashboard_only:
            inventory_hosts.add(host)
        if host == "staging.potaito.pitchai.net" and (is_production or is_dashboard_only):
            raise AssertionError(_LOG_POLICY_ERROR)

    map_hosts: set[str] = set()
    inside_map = False
    for line in config.splitlines():
        if line == "map $host $pitchai_service_monitoring_production {":
            inside_map = True
            continue
        if inside_map and line == "}":
            break
        if inside_map:
            match = re.fullmatch(r"  ([a-z0-9.-]+) 0;", line)
            if match is not None:
                map_hosts.add(match.group(1))
    if "  default 1;" not in config or map_hosts != inventory_hosts:
        raise AssertionError(_LOG_POLICY_ERROR)
