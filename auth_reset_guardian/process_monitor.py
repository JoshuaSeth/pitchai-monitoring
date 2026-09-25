# Copyright (c) 2026 PitchAI. All rights reserved.
"""Drain, bound, terminate, and reap one spawned child process."""

from __future__ import annotations

import os
import selectors
import signal
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from .process_spawn import close_descriptors
from .process_types import ProcessTimeoutError

if TYPE_CHECKING:
    from .process_spawn import ProcessReadDescriptors

_POLL_INTERVAL_SECONDS = 0.05
_READ_CHUNK_BYTES = 8192


@dataclass(slots=True)
class BoundedCapture:
    """Retain at most one declared number of bytes while draining a stream."""

    limit: int
    data: bytearray = field(default_factory=bytearray)
    exceeded: bool = False

    def add(self, chunk: bytes) -> None:
        """Store the permitted prefix and record any discarded overflow."""
        remaining = self.limit - len(self.data)
        if remaining > 0:
            self.data.extend(chunk[:remaining])
        if len(chunk) > remaining:
            self.exceeded = True


@dataclass(slots=True)
class ProcessMonitor:
    """Own child status and selector state throughout stream collection."""

    pid: int
    descriptors: ProcessReadDescriptors
    stdout: BoundedCapture
    stderr: BoundedCapture
    deadline: float
    status: int | None = None
    selector: selectors.BaseSelector = field(
        default_factory=selectors.DefaultSelector,
    )

    def run(self) -> int:
        """Drain both streams and reap or terminate the child.

        Returns:
            The platform child status.

        """
        self.selector.register(
            self.descriptors.stdout,
            selectors.EVENT_READ,
            self.stdout,
        )
        self.selector.register(
            self.descriptors.stderr,
            selectors.EVENT_READ,
            self.stderr,
        )
        while self.selector.get_map() or self.status is None:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                return self._deadline_status()
            wait_seconds = min(_POLL_INTERVAL_SECONDS, remaining)
            for key, _events in self.selector.select(wait_seconds):
                capture = cast("BoundedCapture", key.data)
                if not _drain_stream(key.fd, capture):
                    self.selector.unregister(key.fd)
            if self.status is None:
                completed_pid, completed_status = os.waitpid(self.pid, os.WNOHANG)
                if completed_pid == self.pid:
                    self.status = completed_status
        return self.status

    def _deadline_status(self) -> int:
        """Terminate deadline survivors or their inherited process group.

        Returns:
            The already-reaped leader status when only descendants remain.

        Raises:
            ProcessTimeoutError: If the child leader exceeded its deadline.

        """
        if self.status is None:
            self.status = _terminate_and_reap(self.pid)
            msg = "child process exceeded its timeout"
            raise ProcessTimeoutError(msg)
        _kill_process_group(self.pid)
        return self.status

    def cleanup_after_failure(self) -> None:
        """Terminate every surviving child after an unexpected monitor error."""
        if self.status is None:
            self.status = _terminate_and_reap(self.pid)
        else:
            _kill_process_group(self.pid)

    def close(self) -> None:
        """Close the selector without taking ownership of stream descriptors."""
        self.selector.close()


def capture_process(
    pid: int,
    descriptors: ProcessReadDescriptors,
    *,
    stdout: BoundedCapture,
    stderr: BoundedCapture,
    timeout_seconds: float,
) -> int:
    """Drain child streams and guarantee cleanup after every post-spawn exit.

    Returns:
        The platform child status.

    """
    try:
        monitor = ProcessMonitor(
            pid,
            descriptors,
            stdout,
            stderr,
            deadline=time.monotonic() + timeout_seconds,
        )
    except BaseException:
        try:
            _terminate_and_reap(pid)
        finally:
            close_descriptors((descriptors.stdout, descriptors.stderr))
        raise
    try:
        return monitor.run()
    except BaseException:
        monitor.cleanup_after_failure()
        raise
    finally:
        monitor.close()
        close_descriptors((descriptors.stdout, descriptors.stderr))


def _drain_stream(file_descriptor: int, capture: BoundedCapture) -> bool:
    """Drain one nonblocking stream and report whether it remains open.

    Returns:
        Whether the stream can produce more bytes.

    """
    while True:
        try:
            chunk = os.read(file_descriptor, _READ_CHUNK_BYTES)
        except BlockingIOError:
            return True
        if not chunk:
            return False
        capture.add(chunk)


def _terminate_and_reap(pid: int) -> int:
    """Kill a timed-out child and synchronously consume its wait status.

    Returns:
        The reaped child status.

    """
    _kill_process_group(pid)
    while True:
        try:
            _completed_pid, status = os.waitpid(pid, 0)
        except InterruptedError:
            continue
        return status


def _kill_process_group(pid: int) -> bool:
    """Terminate the child's complete process group when it still exists.

    Returns:
        Whether the process group existed when termination was attempted.

    """
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return False
    return True
