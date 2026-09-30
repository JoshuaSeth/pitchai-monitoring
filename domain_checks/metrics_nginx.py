# Copyright (c) 2026 PitchAI. All rights reserved.
"""Parse bounded nginx access logs and expose upstream-error metrics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .nginx_log import build_log_datetime, read_log_tail
from .nginx_upstream import (
    NginxUpstreamErrorEvent,
    NginxUpstreamErrorSummary,
    parse_recent_upstream_errors,
    summarize_upstream_errors,
)

if TYPE_CHECKING:
    from datetime import datetime

    from .nginx_log import LogDateTimeParts

__all__ = [
    "NginxAccessWindowStats",
    "NginxUpstreamErrorEvent",
    "NginxUpstreamErrorSummary",
    "compute_access_window_stats",
    "parse_recent_upstream_errors",
    "summarize_upstream_errors",
]


_ACCESS_RE = re.compile(
    r'^\S+\s+\S+\s+\S+\s+\[(?P<ts>[^\]]+)\]\s+"(?P<req>[^"]*)"\s+'
    r'(?P<status>\d{3})\s+(?P<size>\S+)\s+"(?P<ref>[^"]*)"\s+"(?P<ua>[^"]*)"',
)
_ACCESS_TIMESTAMP_RE = re.compile(
    r"(?P<day>\d{2})/(?P<month>[A-Z][a-z]{2})/(?P<year>\d{4}):"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2}) "
    r"(?P<offset_sign>[+-])(?P<offset_hour>\d{2})(?P<offset_minute>\d{2})",
)
_MONTH_NUMBERS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
_CLIENT_ERROR_MIN = 400
_SERVER_ERROR_MIN = 500
_SERVER_ERROR_MAX = 600
_BAD_GATEWAY_STATUSES = frozenset({502, 504})
_SAMPLED_GATEWAY_STATUSES = frozenset({502, 503, 504})
_MAX_TIMEZONE_HOUR = 23
_MAX_TIMEZONE_MINUTE = 59


@dataclass(frozen=True)
class NginxAccessWindowStats:
    """HTTP status counters and a bounded failed-request sample."""

    total: int
    status_5xx: int
    status_502_504: int
    status_4xx: int
    sample_lines: list[str]


@dataclass
class _AccessCounts:
    """Mutable counters used while traversing an access-log window."""

    total: int = 0
    status_5xx: int = 0
    status_502_504: int = 0
    status_4xx: int = 0


def _parse_access_sample(line: str) -> tuple[float, int] | None:
    """Parse one combined-log line.

    Returns:
        UTC epoch time and HTTP status, or ``None`` for malformed input.
    """
    match = _ACCESS_RE.match(line.strip())
    if match is None:
        return None
    timestamp_match = _ACCESS_TIMESTAMP_RE.fullmatch(match.group("ts"))
    if timestamp_match is None:
        return None
    month = _MONTH_NUMBERS.get(timestamp_match.group("month"))
    if month is None:
        return None
    date_parts: LogDateTimeParts = (
        int(timestamp_match.group("year")),
        month,
        int(timestamp_match.group("day")),
        int(timestamp_match.group("hour")),
        int(timestamp_match.group("minute")),
        int(timestamp_match.group("second")),
    )
    offset_hour = int(timestamp_match.group("offset_hour"))
    offset_minute = int(timestamp_match.group("offset_minute"))
    valid_offset = (
        offset_hour <= _MAX_TIMEZONE_HOUR and offset_minute <= _MAX_TIMEZONE_MINUTE
    )
    if not valid_offset:
        return None
    offset_minutes = (offset_hour * 60) + offset_minute
    if timestamp_match.group("offset_sign") == "-":
        offset_minutes *= -1
    observed_at = build_log_datetime(
        date_parts,
        local_tz=timezone(timedelta(minutes=offset_minutes)),
    )
    if observed_at is None:
        return None
    return observed_at.astimezone(UTC).timestamp(), int(match.group("status"))


def _record_access_status(counts: _AccessCounts, status: int) -> None:
    """Add one parsed HTTP status to the window counters."""
    counts.total += 1
    counts.status_5xx += int(_SERVER_ERROR_MIN <= status < _SERVER_ERROR_MAX)
    counts.status_502_504 += int(status in _BAD_GATEWAY_STATUSES)
    counts.status_4xx += int(_CLIENT_ERROR_MIN <= status < _SERVER_ERROR_MIN)


def compute_access_window_stats(
    *,
    access_log_path: str,
    now: datetime,
    window_seconds: int,
    max_bytes: int = 1_000_000,
    sample_limit: int = 8,
) -> NginxAccessWindowStats | None:
    """Compute status counters for the configured access-log window.

    Returns:
        Window counters, or ``None`` when the log has no readable content.
    """
    text = read_log_tail(Path(access_log_path), max_bytes=max_bytes)
    if not text.strip():
        return None

    cutoff = now.astimezone(UTC).timestamp() - max(1, window_seconds)
    counts = _AccessCounts()
    samples: list[str] = []
    for line in reversed(text.splitlines()):
        parsed = _parse_access_sample(line)
        if parsed is None:
            continue
        observed_at, status = parsed
        if observed_at < cutoff:
            break
        _record_access_status(counts, status)
        if status in _SAMPLED_GATEWAY_STATUSES and len(samples) < sample_limit:
            samples.append(line.strip()[:800])

    samples.reverse()
    return NginxAccessWindowStats(
        counts.total,
        counts.status_5xx,
        counts.status_502_504,
        counts.status_4xx,
        samples,
    )
