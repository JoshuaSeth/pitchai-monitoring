# Copyright (c) 2026 PitchAI. All rights reserved.
"""Monotonic scheduling and liveness heartbeats for a finite watch."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .evidence import safety_evidence
from .json_types import JsonObject

if TYPE_CHECKING:
    from collections.abc import Callable


def utc_now_iso() -> str:
    """Return a timezone-aware UTC timestamp."""
    current_time = datetime.now(timezone.utc)
    return current_time.isoformat()


@dataclass(frozen=True)
class WatchRuntime:
    """Injectable monotonic, sleep, and wall-clock functions."""

    monotonic: Callable[[], float] = time.monotonic
    sleeper: Callable[[float], None] = time.sleep
    wall_clock: Callable[[], str] = utc_now_iso


def wait_until(
    *,
    due: float,
    cycle_index: int,
    heartbeat_seconds: float,
    runtime: WatchRuntime,
    record: Callable[[JsonObject], None],
) -> None:
    """Wait to a monotonic deadline while recording visible liveness evidence."""
    while True:
        remaining = due - runtime.monotonic()
        if remaining <= 0:
            return
        runtime.sleeper(min(remaining, heartbeat_seconds))
        seconds_left = max(0.0, due - runtime.monotonic())
        if seconds_left > 0:
            event: JsonObject = {
                "event_type": "watch_heartbeat",
                "timestamp_utc": runtime.wall_clock(),
                "next_cycle_index": cycle_index,
                "seconds_until_next_check": round(seconds_left, 3),
                "safety": safety_evidence(0),
            }
            record(event)
            message = " ".join(
                (
                    f"WATCH_HEARTBEAT next_cycle={cycle_index}",
                    f"seconds_until_check={event['seconds_until_next_check']}",
                )
            )
            print(message, flush=True)
