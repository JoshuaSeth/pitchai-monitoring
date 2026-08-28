# Copyright (c) 2026 PitchAI. All rights reserved.
"""Parse bounded Nginx upstream-error log windows."""

from __future__ import annotations

import re
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, NotRequired, TypedDict, Unpack

from .metrics_nginx_io import read_log_tail

if TYPE_CHECKING:
    from datetime import tzinfo

_ERROR_TS_RE = re.compile(
    r"^(?P<ts>\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})\s+\[(?P<level>\w+)\]\s+",
)
_DEFAULT_MAX_BYTES = 1_000_000
_DEFAULT_MAX_EVENTS = 200
_UPSTREAM_FAILURE_MARKERS = (
    "timed out",
    "failed",
    "refused",
    "no live upstreams",
    "upstream prematurely closed",
)
_BUFFERING_WARNING = "upstream response is buffered"
_MAX_EVENT_MESSAGE_LENGTH = 1_000
_MAX_SUMMARY_SAMPLES = 3


@dataclass(frozen=True)
class NginxUpstreamErrorEvent:
    """One relevant Nginx upstream error-log event."""

    ts: str
    level: str
    server: str | None
    upstream: str | None
    message: str


class NginxUpstreamErrorSummary(TypedDict):
    """Counts and bounded samples grouped by Nginx server name."""

    counts_by_server: dict[str, int]
    samples_by_server: dict[str, list[str]]


class _UpstreamLogLimits(TypedDict):
    max_bytes: NotRequired[int]
    max_events: NotRequired[int]


@dataclass(frozen=True)
class _ErrorRecord:
    timestamp: datetime
    timestamp_text: str
    level: str
    message: str


def _extract_kv(line: str, key: str) -> str | None:
    marker = f"{key}: "
    if marker not in line:
        return None
    value = line.split(marker, 1)[1]
    if "," in value:
        value = value.split(",", 1)[0]
    return value.strip().strip('"') or None


def _parse_error_record(line: str, local_tz: tzinfo) -> _ErrorRecord | None:
    stripped_line = line.strip()
    if not stripped_line:
        return None
    match = _ERROR_TS_RE.match(stripped_line)
    if match is None:
        return None
    timestamp: datetime | None = None
    with suppress(ValueError):
        timestamp = datetime.strptime(match.group("ts"), "%Y/%m/%d %H:%M:%S").replace(tzinfo=local_tz)
    if timestamp is None:
        return None
    return _ErrorRecord(
        timestamp=timestamp,
        timestamp_text=match.group("ts"),
        level=match.group("level"),
        message=stripped_line,
    )


def _as_upstream_event(record: _ErrorRecord) -> NginxUpstreamErrorEvent | None:
    lowercase_message = record.message.lower()
    if "upstream" not in lowercase_message and "connect()" not in lowercase_message:
        return None
    has_failure_marker = any(marker in lowercase_message for marker in _UPSTREAM_FAILURE_MARKERS)
    if not has_failure_marker and _BUFFERING_WARNING in lowercase_message:
        return None
    return NginxUpstreamErrorEvent(
        ts=record.timestamp_text,
        level=record.level,
        server=_extract_kv(record.message, "server"),
        upstream=_extract_kv(record.message, "upstream"),
        message=record.message[:_MAX_EVENT_MESSAGE_LENGTH],
    )


def parse_recent_upstream_errors(
    *,
    error_log_path: str,
    now: datetime,
    window_seconds: int,
    local_tz: tzinfo,
    **limits: Unpack[_UpstreamLogLimits],
) -> list[NginxUpstreamErrorEvent]:
    """Return bounded upstream failures from a recent Nginx error-log window.

    Returns:
        Relevant events in chronological order.
    """
    max_bytes = limits.get("max_bytes", _DEFAULT_MAX_BYTES)
    max_events = limits.get("max_events", _DEFAULT_MAX_EVENTS)
    text = read_log_tail(Path(error_log_path), max_bytes=max_bytes)
    if not text.strip():
        return []

    cutoff = now.astimezone(local_tz) - timedelta(seconds=max(1, window_seconds))
    events: list[NginxUpstreamErrorEvent] = []
    for line in reversed(text.splitlines()):
        record = _parse_error_record(line, local_tz)
        if record is None:
            continue
        if record.timestamp < cutoff:
            break
        event = _as_upstream_event(record)
        if event is None:
            continue
        events.append(event)
        if len(events) >= max_events:
            break
    events.reverse()
    return events


def summarize_upstream_errors(events: list[NginxUpstreamErrorEvent]) -> NginxUpstreamErrorSummary:
    """Group upstream errors by Nginx server name with bounded samples.

    Returns:
        Per-server counts and representative log lines.
    """
    counts_by_server: dict[str, int] = {}
    samples_by_server: dict[str, list[str]] = {}
    for event in events:
        server = event.server or "(unknown)"
        counts_by_server[server] = counts_by_server.get(server, 0) + 1
        samples_by_server.setdefault(server, [])
        if len(samples_by_server[server]) < _MAX_SUMMARY_SAMPLES:
            samples_by_server[server].append(event.message)
    return {
        "counts_by_server": counts_by_server,
        "samples_by_server": samples_by_server,
    }
