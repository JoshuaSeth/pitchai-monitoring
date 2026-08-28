# Copyright (c) 2026 PitchAI. All rights reserved.
"""Regression coverage for Nginx self-probe traffic accounting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from .metrics_nginx import SERVICE_MONITOR_USER_AGENT, compute_access_window_stats

if TYPE_CHECKING:
    from pathlib import Path

_EXPECTED_COUNTERS = (2, 1, 1)
_STATS_ERROR = "monitor self-probes changed the customer-traffic Nginx counters"


def test_access_stats_exclude_service_monitor_probes(tmp_path: Path) -> None:
    """Keep synthetic probe outcomes out of the global customer-traffic SLO.

    Raises:
        AssertionError: The parser counts monitor self-probes as customer traffic.
    """
    now = datetime.now(UTC)
    timestamp = (now - timedelta(seconds=10)).strftime("%d/%b/%Y:%H:%M:%S %z")
    synthetic_error = (
        f'1.1.1.1 - - [{timestamp}] "GET /synthetic-error HTTP/1.1" 502 1 '
        f'"-" "{SERVICE_MONITOR_USER_AGENT}"'
    )
    synthetic_success = (
        f'1.1.1.1 - - [{timestamp}] "GET /synthetic-ok HTTP/1.1" 200 1 '
        f'"-" "{SERVICE_MONITOR_USER_AGENT}"'
    )
    customer_error = (
        f'1.1.1.1 - - [{timestamp}] "GET /customer-error HTTP/1.1" 504 1 "-" "customer-agent"'
    )
    customer_success = (
        f'1.1.1.1 - - [{timestamp}] "GET /customer-ok HTTP/1.1" 200 1 "-" "customer-agent"'
    )
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
