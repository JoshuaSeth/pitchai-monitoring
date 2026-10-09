# Copyright (c) 2026 PitchAI. All rights reserved.
"""Parse bounded nginx access logs and expose upstream-error metrics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .nginx_access_record import parse_access_record
from .nginx_log import read_log_tail
from .nginx_upstream import (
    NginxUpstreamErrorEvent,
    NginxUpstreamErrorSummary,
    parse_recent_upstream_errors,
    summarize_upstream_errors,
)

if TYPE_CHECKING:
    from datetime import datetime

__all__ = [
    "NginxAccessWindowStats", "NginxUpstreamErrorEvent", "NginxUpstreamErrorSummary",
    "compute_access_window_stats", "parse_recent_upstream_errors", "summarize_upstream_errors",
]

_CLIENT_ERROR_MIN = 400
_SERVER_ERROR_MIN = 500
_SERVER_ERROR_MAX = 600
_BAD_GATEWAY_STATUSES = frozenset({502, 504})
_SAMPLED_GATEWAY_STATUSES = frozenset({502, 503, 504})
_BOT = "PitchAI Service Monitoring Bot"


@dataclass(frozen=True)
class NginxAccessWindowStats:
    """HTTP status counters and a bounded failed-request sample."""

    total: int
    status_5xx: int
    status_502_504: int
    status_4xx: int
    sample_lines: list[str]


@dataclass(frozen=True)
class AccessHostPolicy:
    """Optional cutover exclusions and sample minimization at the shared feed."""

    excluded: frozenset[str] = frozenset()
    redacted: frozenset[str] = frozenset()
    require_attribution: bool = False
    sample_limit: int = 8


def compute_access_window_stats(
    *, access_log_path: str, now: datetime, window_seconds: int, max_bytes: int = 1_000_000,
    host_policy: AccessHostPolicy | None = None,
) -> NginxAccessWindowStats | None:
    """Compute deployed host-aware JSON or historical combined-log counters.

    Returns:
        Window counters, or None when the shared log has no readable content.

    Raises:
        ValueError: An explicitly scoped transition cannot attribute a record.
    """
    host_policy = host_policy or AccessHostPolicy()
    text = read_log_tail(Path(access_log_path), max_bytes=max_bytes)
    if not text.strip():
        return None
    cutoff = now.timestamp() - max(1, window_seconds)
    counts = [0, 0, 0, 0]
    samples: list[str] = []
    for line in reversed(text.splitlines()):
        record = parse_access_record(line)
        if record is None:
            continue
        if record.timestamp < cutoff or record.timestamp > now.timestamp():
            continue
        if record.agent == _BOT:
            continue
        if host_policy.require_attribution and record.host is None:
            message = "shared_feed_host_unattributed"
            raise ValueError(message)
        if record.host in host_policy.excluded:
            continue
        counts[0] += 1
        counts[1] += int(_SERVER_ERROR_MIN <= record.status < _SERVER_ERROR_MAX)
        counts[2] += int(record.status in _BAD_GATEWAY_STATUSES)
        counts[3] += int(_CLIENT_ERROR_MIN <= record.status < _SERVER_ERROR_MIN)
        sample_allowed = record.host not in host_policy.redacted
        if sample_allowed and record.status in _SAMPLED_GATEWAY_STATUSES and len(samples) < host_policy.sample_limit:
            samples.append(line.strip()[:800])
    samples.reverse()
    return NginxAccessWindowStats(*counts, sample_lines=samples)
