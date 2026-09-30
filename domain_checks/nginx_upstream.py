# Copyright (c) 2026 PitchAI. All rights reserved.
"""Parse and summarize nginx upstream errors at request-burst granularity."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, Unpack

from .nginx_log import build_log_datetime, read_log_tail

if TYPE_CHECKING:
    from datetime import datetime, tzinfo

    from .nginx_log import LogDateTimeParts


_ERROR_TS_RE = re.compile(
    r"^(?P<ts>(?P<year>\d{4})/(?P<month>\d{2})/(?P<day>\d{2})\s+"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2}))\s+"
    r"\[(?P<level>\w+)\]\s+",
)
_ERROR_CONNECTION_RE = re.compile(
    r"\]\s+(?P<worker>\d+#\d+):\s+\*(?P<connection>\d+)\s+",
)
_UPSTREAM_FAILURE_MARKERS = (
    "timed out",
    "failed",
    "refused",
    "no live upstreams",
    "upstream prematurely closed",
)
_BUFFERING_WARNING = "upstream response is buffered"
_MAX_MESSAGE_CHARS = 1_000
_MAX_SAMPLES_PER_SERVER = 3

type RequestBurstKey = tuple[str, str, str, str, str]


@dataclass(frozen=True)
class NginxRequestIdentity:
    """Parsed fields that distinguish requests within one log second."""

    connection_id: str | None = None
    request: str | None = None
    host: str | None = None


@dataclass(frozen=True)
class NginxUpstreamErrorEvent:
    """One raw nginx upstream-error line with parsed request context."""

    ts: str
    level: str
    server: str | None
    upstream: str | None
    message: str
    identity: NginxRequestIdentity = field(default_factory=NginxRequestIdentity)


class NginxUpstreamReadOptions(TypedDict, total=False):
    """Optional bounds for one upstream-error log read."""

    max_bytes: int
    max_events: int


class NginxUpstreamErrorSummary(TypedDict):
    """Request-level counts plus the underlying raw-line evidence."""

    counts_by_server: dict[str, int]
    raw_counts_by_server: dict[str, int]
    duplicate_counts_by_server: dict[str, int]
    samples_by_server: dict[str, list[str]]
    request_event_count: int
    raw_event_count: int


def _extract_context_value(line: str, key: str) -> str | None:
    """Extract one comma-delimited nginx context value.

    Returns:
        The unquoted value, or ``None`` when the key is absent.
    """
    marker = f"{key}: "
    if marker not in line:
        return None
    value = line.split(marker, 1)[1].split(",", 1)[0]
    return value.strip().strip('"') or None


def _extract_connection_id(line: str) -> str | None:
    """Extract the worker-qualified nginx connection identifier.

    Returns:
        A stable worker/connection pair, or ``None`` when unavailable.
    """
    match = _ERROR_CONNECTION_RE.search(line)
    if match is None:
        return None
    return f"{match.group('worker')}:*{match.group('connection')}"


def _is_upstream_failure(line: str) -> bool:
    """Decide whether a line is actionable upstream evidence.

    Returns:
        ``True`` for upstream failures and non-buffering upstream warnings.
    """
    lowered = line.lower()
    if "upstream" not in lowered and "connect()" not in lowered:
        return False
    has_failure_marker = any(marker in lowered for marker in _UPSTREAM_FAILURE_MARKERS)
    return has_failure_marker or _BUFFERING_WARNING not in lowered


def _parse_upstream_event(
    line: str,
    local_tz: tzinfo,
) -> tuple[float, NginxUpstreamErrorEvent] | None:
    """Parse one nginx error line.

    Returns:
        Epoch time and retained raw event, or ``None`` for irrelevant input.
    """
    stripped = line.strip()
    match = _ERROR_TS_RE.match(stripped)
    if match is None or not _is_upstream_failure(stripped):
        return None
    timestamp_text = match.group("ts")
    date_parts: LogDateTimeParts = (
        int(match.group("year")),
        int(match.group("month")),
        int(match.group("day")),
        int(match.group("hour")),
        int(match.group("minute")),
        int(match.group("second")),
    )
    observed_at = build_log_datetime(date_parts, local_tz=local_tz)
    if observed_at is None:
        return None
    event = NginxUpstreamErrorEvent(
        ts=timestamp_text,
        level=match.group("level"),
        server=_extract_context_value(stripped, "server"),
        upstream=_extract_context_value(stripped, "upstream"),
        message=stripped[:_MAX_MESSAGE_CHARS],
        identity=NginxRequestIdentity(
            connection_id=_extract_connection_id(stripped),
            request=_extract_context_value(stripped, "request"),
            host=_extract_context_value(stripped, "host"),
        ),
    )
    return observed_at.timestamp(), event


def parse_recent_upstream_errors(
    *,
    error_log_path: str,
    now: datetime,
    window_seconds: int,
    local_tz: tzinfo,
    **options: Unpack[NginxUpstreamReadOptions],
) -> list[NginxUpstreamErrorEvent]:
    """Read bounded raw upstream errors from the configured log window.

    Returns:
        Raw events in chronological order, capped by ``max_events``.
    """
    max_bytes = options.get("max_bytes", 1_000_000)
    max_events = options.get("max_events", 200)
    text = read_log_tail(Path(error_log_path), max_bytes=max_bytes)
    if not text.strip():
        return []
    cutoff = now.astimezone(local_tz).timestamp() - max(1, window_seconds)
    events: list[NginxUpstreamErrorEvent] = []
    for line in reversed(text.splitlines()):
        parsed = _parse_upstream_event(line, local_tz)
        if parsed is None:
            continue
        observed_at, event = parsed
        if observed_at < cutoff:
            break
        events.append(event)
        if len(events) >= max_events:
            break
    events.reverse()
    return events


def _request_burst_key(event: NginxUpstreamErrorEvent) -> RequestBurstKey | None:
    """Build a request identity that never relies on connection alone.

    Returns:
        A request-burst key, or ``None`` when safe deduplication is impossible.
    """
    identity = event.identity
    if identity.connection_id is None or identity.request is None:
        return None
    return (
        event.ts,
        identity.connection_id,
        event.server or "",
        identity.host or "",
        identity.request,
    )


def summarize_upstream_errors(
    events: list[NginxUpstreamErrorEvent],
) -> NginxUpstreamErrorSummary:
    """Count request bursts per server while retaining raw evidence.

    Returns:
        Request counts, raw counts, duplicate counts, and bounded samples.
    """
    request_counts: dict[str, int] = {}
    raw_counts: dict[str, int] = {}
    samples: dict[str, list[str]] = {}
    seen_bursts: set[RequestBurstKey] = set()
    for event in events:
        server = event.server or "(unknown)"
        raw_counts[server] = raw_counts.get(server, 0) + 1
        server_samples = samples.setdefault(server, [])
        if len(server_samples) < _MAX_SAMPLES_PER_SERVER:
            server_samples.append(event.message)
        burst_key = _request_burst_key(event)
        if burst_key is not None and burst_key in seen_bursts:
            continue
        if burst_key is not None:
            seen_bursts.add(burst_key)
        request_counts[server] = request_counts.get(server, 0) + 1
    duplicate_counts: dict[str, int] = {}
    for server, raw_count in raw_counts.items():
        duplicate_counts[server] = raw_count - request_counts.get(server, 0)
    return {
        "counts_by_server": request_counts,
        "raw_counts_by_server": raw_counts,
        "duplicate_counts_by_server": duplicate_counts,
        "samples_by_server": samples,
        "request_event_count": sum(request_counts.values()),
        "raw_event_count": len(events),
    }
