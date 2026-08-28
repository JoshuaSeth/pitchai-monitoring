# Copyright (c) 2026 PitchAI. All rights reserved.
"""Parse bounded Nginx access-log windows for customer traffic."""

from __future__ import annotations

import json
import re
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from .metrics_nginx_io import read_log_tail
from .metrics_nginx_upstream import (
    NginxUpstreamErrorEvent,
    NginxUpstreamErrorSummary,
    parse_recent_upstream_errors,
    summarize_upstream_errors,
)

__all__ = [
    "SERVICE_MONITOR_USER_AGENT",
    "NginxAccessWindowStats",
    "NginxUpstreamErrorEvent",
    "NginxUpstreamErrorSummary",
    "compute_access_window_stats",
    "parse_recent_upstream_errors",
    "summarize_upstream_errors",
]

_ACCESS_RE = re.compile(
    r"^\S+\s+\S+\s+\S+\s+\[(?P<ts>[^\]]+)\]\s+"
    r'"(?P<req>[^"]*)"\s+(?P<status>\d{3})\s+(?P<size>\S+)\s+'
    r'"(?P<ref>[^"]*)"\s+"(?P<ua>[^"]*)"(?:\s+"(?P<host>[^"]*)")?\s*$',
)

SERVICE_MONITOR_USER_AGENT = "PitchAI Service Monitoring Bot"

_DEFAULT_MAX_BYTES = 1_000_000
_CLIENT_ERROR_MIN = 400
_SERVER_ERROR_MIN = 500
_STATUS_FAMILY_SIZE = 100
_PROXY_ERROR_STATUSES = frozenset({502, 504})
_SAMPLED_ERROR_STATUSES = frozenset({502, 503, 504})
_MAX_SAMPLE_LENGTH = 800


@dataclass(frozen=True)
class NginxAccessWindowStats:
    """Status counters for customer traffic in one Nginx access window."""

    total: int
    status_5xx: int
    status_502_504: int
    status_4xx: int
    sample_lines: list[str]


@dataclass(frozen=True)
class _AccessRecord:
    timestamp: datetime
    status: int
    user_agent: str
    host: str | None
    line: str


@dataclass
class _AccessAccumulator:
    total: int = 0
    status_5xx: int = 0
    status_502_504: int = 0
    status_4xx: int = 0
    samples: list[str] = field(default_factory=list)

    def record(self, record: _AccessRecord, *, sample_limit: int) -> None:
        """Add one customer request to the mutable counters."""
        self.total += 1
        if _SERVER_ERROR_MIN <= record.status < _SERVER_ERROR_MIN + _STATUS_FAMILY_SIZE:
            self.status_5xx += 1
        if record.status in _PROXY_ERROR_STATUSES:
            self.status_502_504 += 1
        if _CLIENT_ERROR_MIN <= record.status < _SERVER_ERROR_MIN:
            self.status_4xx += 1
        if record.status in _SAMPLED_ERROR_STATUSES and len(self.samples) < sample_limit:
            self.samples.append(record.line[:_MAX_SAMPLE_LENGTH])

    def to_window_stats(self) -> NginxAccessWindowStats:
        """Freeze the counters with samples restored to chronological order.

        Returns:
            Immutable counters and ordered sample lines.
        """
        ordered_samples = list(reversed(self.samples))
        return NginxAccessWindowStats(
            total=self.total,
            status_5xx=self.status_5xx,
            status_502_504=self.status_502_504,
            status_4xx=self.status_4xx,
            sample_lines=ordered_samples,
        )


def _normalize_host(value: str) -> str | None:
    normalized = value.strip().lower().rstrip(".")
    return normalized or None


def _parse_json_access_record(stripped_line: str) -> _AccessRecord | None:
    with suppress(json.JSONDecodeError):
        decoded = cast("object", json.loads(stripped_line))
        if not isinstance(decoded, dict):
            return None
        payload = cast("dict[str, object]", decoded)
        timestamp_value = payload.get("timestamp")
        status_value = payload.get("status")
        host_value = payload.get("host")
        user_agent_value = payload.get("user_agent")
        if (
            not isinstance(timestamp_value, str)
            or not isinstance(status_value, int)
            or isinstance(status_value, bool)
            or not isinstance(host_value, str)
            or not isinstance(user_agent_value, str)
        ):
            return None
        timestamp: datetime | None = None
        with suppress(ValueError):
            parsed_timestamp = datetime.fromisoformat(timestamp_value)
            if parsed_timestamp.tzinfo is not None:
                timestamp = parsed_timestamp.astimezone(UTC)
        host = _normalize_host(host_value)
        if timestamp is None or host is None:
            return None
        return _AccessRecord(
            timestamp=timestamp,
            status=status_value,
            user_agent=user_agent_value,
            host=host,
            line=stripped_line,
        )
    return None


def _parse_combined_access_record(stripped_line: str) -> _AccessRecord | None:
    match = _ACCESS_RE.match(stripped_line)
    if match is None:
        return None
    timestamp: datetime | None = None
    with suppress(ValueError):
        timestamp = datetime.strptime(match.group("ts"), "%d/%b/%Y:%H:%M:%S %z").astimezone(UTC)
    if timestamp is None:
        return None
    return _AccessRecord(
        timestamp=timestamp,
        status=int(match.group("status")),
        user_agent=match.group("ua"),
        host=_normalize_host(match.group("host") or ""),
        line=stripped_line,
    )


def _parse_access_record(line: str) -> _AccessRecord | None:
    stripped_line = line.strip()
    if stripped_line.startswith("{"):
        return _parse_json_access_record(stripped_line)
    return _parse_combined_access_record(stripped_line)


def compute_access_window_stats(
    *,
    access_log_path: str,
    now: datetime,
    window_seconds: int,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    sample_limit: int = 8,
) -> NginxAccessWindowStats | None:
    """Compute scoped customer counters while excluding monitor self-probes.

    Returns:
        Window statistics, or ``None`` when the access log has no readable text.
    """
    text = read_log_tail(Path(access_log_path), max_bytes=max_bytes)
    if not text.strip():
        return None

    cutoff = now.astimezone(UTC) - timedelta(seconds=max(1, window_seconds))
    accumulator = _AccessAccumulator()
    for line in reversed(text.splitlines()):
        record = _parse_access_record(line)
        if record is None:
            continue
        if record.timestamp < cutoff:
            break
        if record.user_agent == SERVICE_MONITOR_USER_AGENT:
            continue
        accumulator.record(record, sample_limit=max(0, sample_limit))
    return accumulator.to_window_stats()
