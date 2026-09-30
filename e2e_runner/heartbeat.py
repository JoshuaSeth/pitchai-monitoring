# Copyright (c) 2026 PitchAI. All rights reserved.
"""Runner liveness heartbeat consumed by the monitoring health contract."""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable

type JobValue = str | int | float | bool | None
type HeartbeatDocument = dict[str, JobValue]

PHASE_IDLE: Final = "idle"
PHASE_CLAIMING: Final = "claiming"
PHASE_RUNNING: Final = "running"
HEARTBEAT_VERSION: Final = 1

_TEST_ID_FRAGMENT = re.compile(r"\A[A-Za-z0-9_.:-]{1,64}\Z")


def narrow_test_id(value: JobValue) -> str:
    """Return a narrow test identifier, empty when the value is unusable.

    The runner package must not import the monitoring package, so this narrow
    token rule is kept here instead of reusing the monitoring sanitizer.

    Args:
        value: Claimed job field that may hold arbitrary text.

    Returns:
        The identifier when it is already a narrow printable token.
    """
    text = value if isinstance(value, str) else ""
    return text if _TEST_ID_FRAGMENT.match(text) else ""


@dataclass
class RunnerCounters:
    """Claim and job counters recorded by the runner loop.

    Attributes:
        claim_successes: Claims that returned, including empty claims.
        attempts_since_success: Attempts since the last successful claim.
        last_claim_error: Narrow failure class of the last failed claim, if any.
        completed_jobs: Claimed tests that finished, passed or failed.
        active_job_test_id: Test currently executing, ``None`` when idle.
        active_job_started_ts: Start stamp of the in-flight test, when running.
        last_job_finished_ts: Stamp of the last finished test, when there was one.
    """

    claim_successes: int = 0
    attempts_since_success: int = 0
    last_claim_error: str | None = None
    completed_jobs: int = 0
    active_job_test_id: str | None = None
    active_job_started_ts: float | None = None
    last_job_finished_ts: float | None = None


class RunnerHeartbeat:
    """Thread-safe record of the runner loop progress.

    The record is refreshed by the runner loop itself, so a loop that stops
    making progress is visible even while the process and the publisher thread
    stay alive. Persistence is a separate step, which keeps a failing write
    from changing runner behaviour.

    Attributes:
        _path: Heartbeat document written for the health contract.
        _clock: Epoch clock used for every recorded stamp.
        _lock: Serializes every mutation and snapshot.
        _counters: Claim and job counters owned by the runner loop.
        _started_at_ts: Process-local start stamp of this record.
        _updated_at_ts: Stamp of the last loop progress transition.
        _phase: Loop phase, ``idle`` until the loop starts claiming.
    """

    _lock: threading.Lock
    _path: Path
    _clock: Callable[[], float]
    _counters: RunnerCounters
    _started_at_ts: float
    _updated_at_ts: float
    _phase: str

    def __init__(self, *, path: Path, clock: Callable[[], float] = time.time) -> None:
        """Initialize one idle heartbeat record for the current process.

        Args:
            path: Heartbeat document written for the health contract.
            clock: Epoch clock used for every recorded stamp.
        """
        self._path = path
        self._clock = clock
        self._lock = threading.Lock()
        self._counters = RunnerCounters()
        started_at_ts = float(clock())
        self._started_at_ts = started_at_ts
        self._updated_at_ts = started_at_ts
        self._phase = PHASE_IDLE

    def record_claim_attempt(self) -> None:
        """Record that the loop started one registry claim attempt."""
        with self._lock:
            self._phase = PHASE_CLAIMING
            self._counters.attempts_since_success += 1
            self._touch()

    def record_claim_success(self) -> None:
        """Record a completed claim, including a legitimate empty claim."""
        with self._lock:
            self._counters.claim_successes += 1
            self._counters.attempts_since_success = 0
            self._counters.last_claim_error = None
            self._phase = PHASE_IDLE
            self._touch()

    def record_claim_error(self, *, error_class: str) -> None:
        """Retain the narrow failure class of one failed claim attempt."""
        with self._lock:
            self._counters.last_claim_error = narrow_test_id(error_class) or None
            self._touch()

    def record_job_start(self, *, test_id: str) -> None:
        """Record that one claimed test moved into execution."""
        with self._lock:
            self._phase = PHASE_RUNNING
            self._counters.active_job_test_id = test_id or None
            self._counters.active_job_started_ts = float(self._clock())
            self._touch()

    def record_job_finish(self) -> None:
        """Record that the in-flight test finished, passed or failed."""
        with self._lock:
            self._counters.completed_jobs += 1
            self._counters.last_job_finished_ts = float(self._clock())
            self._counters.active_job_test_id = None
            self._counters.active_job_started_ts = None
            self._phase = PHASE_IDLE
            self._touch()

    def snapshot(self) -> HeartbeatDocument:
        """Return the current heartbeat document as JSON-compatible values."""
        with self._lock:
            counters = self._counters
            return {
                "version": HEARTBEAT_VERSION,
                "phase": self._phase,
                "updated_at_ts": self._updated_at_ts,
                "started_at_ts": self._started_at_ts,
                # Every attempt either succeeds or extends the failure streak.
                "claim_attempts": counters.claim_successes + counters.attempts_since_success,
                "claim_successes": counters.claim_successes,
                "consecutive_claim_failures": counters.attempts_since_success,
                "last_claim_error": counters.last_claim_error,
                "completed_jobs": counters.completed_jobs,
                "active_job_test_id": counters.active_job_test_id,
                "active_job_started_ts": counters.active_job_started_ts,
                "last_job_finished_ts": counters.last_job_finished_ts,
            }

    def write(self) -> None:
        """Replace the heartbeat document atomically."""
        payload = json.dumps(self.snapshot(), ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        temporary = self._path.with_name(f".{self._path.name}.tmp")
        _ = temporary.write_text(payload, encoding="utf-8")
        _ = Path(temporary).replace(self._path)

    def _touch(self) -> None:
        self._updated_at_ts = float(self._clock())


def start_heartbeat_publisher(*, heartbeat: RunnerHeartbeat, interval_seconds: float) -> threading.Thread:
    """Start the daemon thread that persists the heartbeat on a fixed cadence.

    Args:
        heartbeat: Record to persist.
        interval_seconds: Delay between two persisted snapshots.

    Returns:
        The started daemon thread.
    """
    thread = threading.Thread(
        target=_publish_forever,
        args=(heartbeat, interval_seconds),
        name="runner-heartbeat",
        daemon=True,
    )
    thread.start()
    return thread


def _publish_forever(heartbeat: RunnerHeartbeat, interval_seconds: float) -> None:
    while True:
        heartbeat.write()
        time.sleep(interval_seconds)
