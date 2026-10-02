# Copyright (c) 2026 PitchAI. All rights reserved.
"""Read production DFT hourly segments without retaining request content."""

from __future__ import annotations

import json
import math
from contextlib import suppress
from typing import TYPE_CHECKING, cast

from .dft_segment_io import SegmentUnavailableError, load_window
from .metrics_nginx import NginxAccessWindowStats

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from .dft_segment_io import SegmentSnapshot
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
        and math.isfinite(timestamp) and hour_start <= timestamp < hour_start + _HOUR_SECONDS
        and isinstance(status, int) and not isinstance(status, bool) and _STATUS_MIN <= status <= _STATUS_MAX
        and isinstance(agent, str)
    )
    if not valid:
        message = "invalid_segment_record"
        raise SegmentUnavailableError(message)
    return float(cast("float", timestamp)), cast("int", status), cast("str", agent)


def _count_segments(segments: list[tuple[str, float, bytes]], start: float, end: float) -> NginxAccessWindowStats:
    counts = [0, 0, 0, 0]
    for capture, hour_start, data in segments:
        for line in data.splitlines(keepends=True):
            if not line.endswith(b"\n"):
                continue
            timestamp, status, agent = _record(line, capture, hour_start)
            if not start <= timestamp <= end or agent == _BOT:
                continue
            counts[0] += 1
            counts[1] += int(status >= _SERVER_ERROR_MIN)
            counts[2] += int(status in {502, 504})
            counts[3] += int(_CLIENT_ERROR_MIN <= status < _SERVER_ERROR_MIN)
    return NginxAccessWindowStats(*counts, sample_lines=[])


def read_production_window(
    root: Path,
    *,
    now: datetime,
    window_seconds: int,
    max_bytes: int = 1_000_000,
    snapshots: dict[str, SegmentSnapshot] | None = None,
) -> NginxAccessWindowStats:
    """Recompute one complete production window without accumulating polls.

    Caller binds the root to production and retains metadata snapshots across
    cycles. Each physical segment/byte position is visited once per window;
    identical records at different positions remain distinct requests. A final
    partial record waits for completion. Staging siblings are never traversed.

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
    segments, next_snapshots = load_window(root, start=start, end=end, max_bytes=max_bytes, previous=retained)
    result = _count_segments(segments, start, end)
    retained.clear()
    retained.update(next_snapshots)
    return result
