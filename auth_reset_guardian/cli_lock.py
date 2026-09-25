# Copyright (c) 2026 PitchAI. All rights reserved.
"""Provide bounded cross-process locking for guardian CLI commands."""

from __future__ import annotations

import argparse
import fcntl
import math
import os
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_MAX_LOCK_WAIT_SECONDS = 600


def bounded_lock_wait(value: str) -> float:
    """Parse a finite lock-wait duration within the CLI safety bound.

    Returns:
        The computed value.

    Raises:
        ArgumentTypeError: If the operation violates its documented contract.

    """
    try:
        parsed = float(value)
    except ValueError as exc:
        msg = "lock wait must be a number"
        raise argparse.ArgumentTypeError(msg) from exc
    if not math.isfinite(parsed) or parsed < 0 or parsed > _MAX_LOCK_WAIT_SECONDS:
        msg = "lock wait must be between 0 and 600 seconds"
        raise argparse.ArgumentTypeError(msg)
    return parsed


@contextmanager
def exclusive_lock(audit_path: Path, *, wait_seconds: float = 0.0) -> Generator[None]:
    """Hold the audit-specific process lock for the managed block."""
    descriptor = _open_locked_descriptor(audit_path, wait_seconds=wait_seconds)
    try:
        yield
    finally:
        os.close(descriptor)


def _open_locked_descriptor(audit_path: Path, *, wait_seconds: float) -> int:
    resolved = audit_path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = resolved.with_suffix(resolved.suffix + ".lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        _acquire_descriptor(descriptor, wait_seconds=wait_seconds)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _acquire_descriptor(descriptor: int, *, wait_seconds: float) -> None:
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            lock_result = fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _raise_lock_timeout(wait_seconds)
            time.sleep(min(0.1, remaining))
        else:
            del lock_result
            return


def _raise_lock_timeout(wait_seconds: float) -> None:
    if wait_seconds:
        msg = f"another reset guardian run held the audit lock beyond {wait_seconds:g} seconds"
        raise SystemExit(msg)
    msg = "another reset guardian run holds the audit lock"
    raise SystemExit(msg)
