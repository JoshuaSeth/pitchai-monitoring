# Copyright (c) 2026 PitchAI. All rights reserved.
"""Independent-process helpers for sandbox UID lease and recovery probes."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

from e2e_runner.uid_lease_config import LEASE_DIRECTORY_ENVIRONMENT
from e2e_runner.uid_leases import release_uid_lease, try_acquire_uid_lease

if TYPE_CHECKING:
    from multiprocessing.synchronize import Event

SANDBOX_GID = 65_534
CHILD_WAIT_SECONDS = 120


def attempt_uid_lease(uid: int, lease_directory: str, result_path: str) -> None:
    """Record whether an independent interpreter can acquire one UID lease."""
    os.environ[LEASE_DIRECTORY_ENVIRONMENT] = lease_directory
    lease = try_acquire_uid_lease(uid)
    outcome = "blocked" if lease is None else "acquired"
    Path(result_path).write_text(outcome, encoding="utf-8")
    if lease is not None:
        release_uid_lease(lease)


def leave_dirty_uid_lease(uid: int, lease_directory: str, result_path: str) -> None:
    """Exit normally without lifecycle release, modeling supervisor death."""
    os.environ[LEASE_DIRECTORY_ENVIRONMENT] = lease_directory
    lease = try_acquire_uid_lease(uid)
    if lease is None:
        Path(result_path).write_text("blocked", encoding="utf-8")
        return
    Path(result_path).write_text("active", encoding="utf-8")
    # Process teardown closes the descriptor while the crash-visible state stays active.


def hold_sandbox_uid(uid: int, ready: Event) -> None:
    """Drop permanently to one sandbox UID and remain alive for recovery."""
    os.setgroups([])
    os.setgid(SANDBOX_GID)
    os.setuid(uid)
    ready.set()
    time.sleep(CHILD_WAIT_SECONDS)
