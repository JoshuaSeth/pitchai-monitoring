# Copyright (c) 2026 PitchAI. All rights reserved.
"""Bounded Nginx access and error-log analysis."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NamedTuple, NotRequired, TypedDict, Unpack

from domain_checks.nginx_log_io import tail_bytes

if TYPE_CHECKING:
    from datetime import tzinfo

_ACCESS_RE = re.compile(
    r'^\S+\s+\S+\s+\S+\s+\[(?P<ts>[^\]]+)\]\s+"(?P<req>[^"]*)"\s+'
    r'(?P<status>\d{3})\s+(?P<size>\S+)\s+"(?P<ref>[^"]*)"\s+'
    r'"(?P<ua>[^"]*)"',
)
_ERROR_TS_RE = re.compile(
    r"^(?P<ts>\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"\[(?P<level>\w+)\]\s+",
)

_CLIENT_ERROR_MIN = 400
_SERVER_ERROR_MIN = 500
_STATUS_MAX_EXCLUSIVE = 600
_UPSTREAM_SAMPLE_LIMIT = 3


@dataclass(frozen=True)
class NginxAccessWindowStats:
    """Summarize status codes in a recent access-log window."""

    total: int
    status_5xx: int
    status_502_504: int
    status_4xx: int
    sample_lines: list[str]


class _AccessEntry(NamedTuple):
    timestamp: float
    status: int


def _parse_access_entry(line: str) -> _AccessEntry | None:
    match = _ACCESS_RE.match(line.strip())
    if match is None:
        return None
    try:
        timestamp = (
            datetime
            .strptime(
                match.group("ts"),
                "%d/%b/%Y:%H:%M:%S %z",
            )
            .astimezone(UTC)
            .timestamp()
        )
    except ValueError:
        return None
    try:
        status = int(match.group("status"))
    except ValueError:
        status = 0
    return _AccessEntry(timestamp, status)


def compute_access_window_stats(
    *,
    access_log_path: str,
    now: datetime,
    window_seconds: int,
    max_bytes: int = 1_000_000,
    sample_limit: int = 8,
) -> NginxAccessWindowStats | None:
    """Compute recent Nginx access status counts and bounded failure samples.

    Returns:
        Recent access-log statistics, or ``None`` when the log is empty.
    """
    text = tail_bytes(access_log_path, max_bytes=int(max_bytes))
    if not text.strip():
        return None
    cutoff = now.astimezone(UTC).timestamp() - max(1, int(window_seconds))
    total = status_5xx = status_502_504 = status_4xx = 0
    samples: list[str] = []
    for line in reversed(text.splitlines()):
        entry = _parse_access_entry(line)
        if entry is None:
            continue
        if entry.timestamp < cutoff:
            break
        total += 1
        status_5xx += int(_SERVER_ERROR_MIN <= entry.status < _STATUS_MAX_EXCLUSIVE)
        status_502_504 += int(entry.status in {502, 504})
        status_4xx += int(_CLIENT_ERROR_MIN <= entry.status < _SERVER_ERROR_MIN)
        if entry.status in {502, 503, 504} and len(samples) < int(sample_limit):
            samples.append(line.strip()[:800])
    samples.reverse()
    return NginxAccessWindowStats(
        total=total,
        status_5xx=status_5xx,
        status_502_504=status_502_504,
        status_4xx=status_4xx,
        sample_lines=samples,
    )


@dataclass(frozen=True)
class NginxUpstreamErrorEvent:
    """Represent one relevant Nginx upstream error event."""

    ts: str
    level: str
    server: str | None
    upstream: str | None
    message: str


class NginxErrorOptions(TypedDict):
    """Optional bounds accepted by error-log parsing."""

    max_bytes: NotRequired[int]
    max_events: NotRequired[int]


def _extract_kv(line: str, key: str) -> str | None:
    marker = f"{key}: "
    if marker not in line:
        return None
    value = line.split(marker, 1)[1]
    if "," in value:
        value = value.split(",", 1)[0]
    return value.strip().strip('"') or None


def _relevant_upstream_error(line: str) -> bool:
    lowered = line.lower()
    if "upstream" not in lowered and "connect()" not in lowered:
        return False
    signals = (
        "timed out",
        "failed",
        "refused",
        "no live upstreams",
        "upstream prematurely closed",
    )
    if any(signal in lowered for signal in signals):
        return True
    return "upstream response is buffered" not in lowered


class _TimestampedError(NamedTuple):
    timestamp: float
    event: NginxUpstreamErrorEvent


def _parse_error_event(line: str, local_tz: tzinfo) -> _TimestampedError | None:
    stripped = line.strip()
    match = _ERROR_TS_RE.match(stripped)
    if match is None or not _relevant_upstream_error(stripped):
        return None
    timestamp_text = match.group("ts")
    try:
        timestamp = (
            datetime
            .strptime(
                timestamp_text,
                "%Y/%m/%d %H:%M:%S",
            )
            .replace(tzinfo=local_tz)
            .timestamp()
        )
    except ValueError:
        return None
    event = NginxUpstreamErrorEvent(
        ts=timestamp_text,
        level=match.group("level"),
        server=_extract_kv(stripped, "server"),
        upstream=_extract_kv(stripped, "upstream"),
        message=stripped[:1000],
    )
    return _TimestampedError(timestamp, event)


def parse_recent_upstream_errors(
    *,
    error_log_path: str,
    now: datetime,
    window_seconds: int,
    local_tz: tzinfo,
    **options: Unpack[NginxErrorOptions],
) -> list[NginxUpstreamErrorEvent]:
    """Parse recent, relevant upstream errors from an Nginx error log.

    Returns:
        Relevant upstream failures ordered from oldest to newest.
    """
    max_bytes = int(options.get("max_bytes", 1_000_000))
    max_events = int(options.get("max_events", 200))
    text = tail_bytes(error_log_path, max_bytes=max_bytes)
    if not text.strip():
        return []
    cutoff = now.astimezone(local_tz).timestamp() - max(1, int(window_seconds))
    events: list[NginxUpstreamErrorEvent] = []
    for line in reversed(text.splitlines()):
        parsed = _parse_error_event(line, local_tz)
        if parsed is None:
            continue
        if parsed.timestamp < cutoff:
            break
        events.append(parsed.event)
        if len(events) >= max_events:
            break
    events.reverse()
    return events


class NginxUpstreamSummary(TypedDict):
    """Aggregate upstream failure counts and samples by server."""

    counts_by_server: dict[str, int]
    samples_by_server: dict[str, list[str]]


def summarize_upstream_errors(
    events: list[NginxUpstreamErrorEvent],
) -> NginxUpstreamSummary:
    """Aggregate upstream failure counts and bounded samples by server.

    Returns:
        Counts and bounded message samples grouped by server.
    """
    counts: dict[str, int] = {}
    samples: dict[str, list[str]] = {}
    for event in events:
        server = event.server or "(unknown)"
        counts[server] = int(counts.get(server, 0)) + 1
        samples.setdefault(server, [])
        if len(samples[server]) < _UPSTREAM_SAMPLE_LIMIT:
            samples[server].append(event.message)
    return {"counts_by_server": counts, "samples_by_server": samples}
