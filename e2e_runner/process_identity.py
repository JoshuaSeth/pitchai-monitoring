# Copyright (c) 2026 PitchAI. All rights reserved.
"""Stable Linux process identity handles for sandbox cleanup."""

from __future__ import annotations

import asyncio
import os
import signal
from dataclasses import dataclass
from pathlib import Path

from e2e_runner.pidfd_gateway import PIDFD_GATEWAY


@dataclass(frozen=True)
class ProcessHandle:
    """A PID plus a pidfd that remains bound across numeric PID reuse."""

    pid: int
    descriptor: int


def _process_identity(path: Path) -> tuple[int, str]:
    owner_uid = path.stat().st_uid
    process_stat = (path / "stat").read_text(encoding="utf-8")
    state = process_stat.rsplit(")", maxsplit=1)[1].strip().split(maxsplit=1)[0]
    return owner_uid, state


def _owned_process_handles(uid: int) -> list[ProcessHandle]:
    handles: list[ProcessHandle] = []
    proc_entries = Path("/proc").iterdir()
    numeric_entries = (path for path in proc_entries if path.name.isdigit())
    process_paths = list(numeric_entries)
    for path in process_paths:
        pid = int(path.name)
        try:
            descriptor = PIDFD_GATEWAY.open(pid)
        except ProcessLookupError:
            continue
        try:
            owner_uid, state = _process_identity(path)
        except (FileNotFoundError, ProcessLookupError):
            os.close(descriptor)
            continue
        except (OSError, ValueError, IndexError):
            os.close(descriptor)
            raise
        if owner_uid == uid and state not in {"X", "Z"}:
            handles.append(ProcessHandle(pid=pid, descriptor=descriptor))
        else:
            os.close(descriptor)
    return handles


async def owned_process_handles(uid: int) -> list[ProcessHandle]:
    """Return pidfds for every currently live process owned by ``uid``."""
    return await asyncio.to_thread(_owned_process_handles, uid)


def uid_has_live_processes(uid: int) -> bool:
    """Check UID availability through stable pidfds, closing every probe handle.

    Returns:
        Whether a non-zombie process currently owns the UID.
    """
    handles = _owned_process_handles(uid)
    try:
        return bool(handles)
    finally:
        for handle in handles:
            os.close(handle.descriptor)


def kill_process_handle(handle: ProcessHandle) -> None:
    """Signal exactly the process bound to a pidfd, never a reused numeric PID."""
    try:
        PIDFD_GATEWAY.signal(handle.descriptor, signal.SIGKILL)
    finally:
        os.close(handle.descriptor)
