# Copyright (c) 2026 PitchAI. All rights reserved.
"""Read production DFT hourly segments without retaining request content."""

from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import replace
from typing import TYPE_CHECKING, cast

from .dft_segment_io import SegmentCount, SegmentUnavailableError, load_window
from .metrics_nginx import NginxAccessWindowStats

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from .dft_segment_io import SegmentChunk, SegmentSnapshot
    from .event_bus_delivery import JsonValue

_BOT = "PitchAI Service Monitoring Bot"
_STATUS_MIN = 100
_STATUS_MAX = 599
_CLIENT_ERROR_MIN = 400
_SERVER_ERROR_MIN = 500
_HOUR_SECONDS = 3600


def _record(line: bytes, capture: str, hour_start: float) -> tuple[float, int, str]:
    """Validate the producer schema at its JSON boundary.

    Returns:
        Original request epoch, status and transient user agent.

    Raises:
        SegmentUnavailableError: The complete record cannot be trusted.
    """
    record: JsonValue = None
    with suppress(ValueError, RecursionError):
        record = cast("JsonValue", json.loads(line))
    if not isinstance(record, dict):
        message = "invalid_segment_record"
        raise SegmentUnavailableError(message)
    timestamp, status, agent = record.get("event_unix"), record.get("status"), record.get("agent")
    valid = (
        record.get("class") == "dft-web-access-v1" and record.get("capture_hour") == capture
        and isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool)
        and hour_start <= timestamp < hour_start + _HOUR_SECONDS
        and isinstance(status, int) and not isinstance(status, bool) and _STATUS_MIN <= status <= _STATUS_MAX
        and isinstance(agent, str)
    )
    if not valid:
        message = "invalid_segment_record"
        raise SegmentUnavailableError(message)
    return float(cast("float", timestamp)), cast("int", status), cast("str", agent)


def _consume(chunk: SegmentChunk, start: float) -> SegmentSnapshot:
    retained_counts = (item for item in chunk.snapshot.counts if item.timestamp >= start)
    counts = {item.timestamp: item for item in retained_counts}
    consumed = 0
    for line in chunk.data.splitlines(keepends=True):
        if not line.endswith(b"\n"):
            break
        timestamp, status, agent = _record(line, chunk.capture, chunk.hour)
        consumed += len(line)
        if timestamp < start or agent == _BOT:
            continue
        old = counts.get(timestamp, SegmentCount(timestamp, 0, 0, 0, 0))
        counts[timestamp] = SegmentCount(timestamp, old.total + 1, old.server_errors + int(status >= _SERVER_ERROR_MIN),
                                        old.gateway_errors + int(status in {502, 504}),
                                        old.client_errors + int(_CLIENT_ERROR_MIN <= status < _SERVER_ERROR_MIN))
    return replace(chunk.snapshot, offset=chunk.snapshot.offset + consumed, covered_start=start,
                   counts=tuple(counts.values()))


def read_production_window(
    root: Path,
    *,
    now: datetime,
    window_seconds: int,
    max_bytes: int = 1_000_000,
    snapshots: dict[str, SegmentSnapshot] | None = None,
) -> NginxAccessWindowStats:
    """Advance bounded byte cursors and count only a completely covered window.

    Caller binds the root to production and retains metadata snapshots across
    cycles. Each complete physical segment/byte position is consumed once;
    identical records at different positions remain distinct requests. A final
    partial record waits for completion. Cold catch-up persists only validated
    cursor/counter progress and reports unavailable coverage until caught up.
    Staging siblings are never traversed.

    Returns:
        Aggregate status counters without any raw request samples.

    Raises:
        SegmentUnavailableError: Window arguments or complete records are invalid.
    """
    if now.tzinfo is None or window_seconds <= 0 or max_bytes <= 0:
        message = "invalid_window"
        raise SegmentUnavailableError(message)
    end = now.timestamp()
    start = end - window_seconds
    retained = {} if snapshots is None else snapshots
    segments = load_window(root, start=start, end=end, max_bytes=max_bytes, previous=retained)
    next_snapshots = {f"dft-access-{chunk.capture}.jsonl": _consume(chunk, start) for chunk in segments}
    retained.clear()
    retained.update(next_snapshots)
    if any(not chunk.reached_end for chunk in segments):
        message = "segment_catchup_incomplete"
        raise SegmentUnavailableError(message)
    counts = [0, 0, 0, 0]
    for snapshot in retained.values():
        for item in snapshot.counts:
            if item.timestamp <= end:
                counts[0] += item.total
                counts[1] += item.server_errors
                counts[2] += item.gateway_errors
                counts[3] += item.client_errors
    return NginxAccessWindowStats(*counts, sample_lines=[])
