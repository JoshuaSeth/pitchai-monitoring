# Copyright (c) 2026 PitchAI. All rights reserved.
"""Cross-process, crash-visible sandbox UID leases."""

from __future__ import annotations

import fcntl
import os
import stat
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from e2e_runner.process_identity import uid_has_live_processes
from e2e_runner.uid_lease_config import SandboxLeaseError, prepare_lease_directory

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_LEASE_MODE = 0o600
_ACTIVE_STATE = "active"
_CLEAN_STATE = "clean"
_LEASE_FIELD_COUNT = 2


@dataclass(frozen=True)
class SandboxUidLease:
    """One file-description lock held for the complete UID lifecycle."""

    uid: int
    descriptor: int
    path: Path


def recorded_lease_uids() -> set[int]:
    """Return UIDs with persisted lease state, rejecting unexpected entries.

    Returns:
        Every UID represented by a validated lease filename.

    Raises:
        SandboxLeaseError: If the lease directory contains an invalid entry.
    """
    directory = prepare_lease_directory()
    recorded: set[int] = set()
    for path in directory.iterdir():
        if not path.name.startswith("uid-") or not path.name.endswith(".lease"):
            message = f"unexpected sandbox lease directory entry: {path}"
            raise SandboxLeaseError(message)
        uid_text = path.name.removeprefix("uid-").removesuffix(".lease")
        if not uid_text.isdigit():
            message = f"invalid sandbox lease filename: {path}"
            raise SandboxLeaseError(message)
        recorded.add(int(uid_text))
    return recorded


def _open_lease_file(uid: int) -> tuple[int, Path]:
    directory = prepare_lease_directory()
    path = directory / f"uid-{uid}.lease"
    flags = os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW
    with _exclusive_directory_lock(directory):
        try:
            descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, _LEASE_MODE)
        except FileExistsError:
            descriptor = os.open(path, flags)
        else:
            _write_state(descriptor, state=_CLEAN_STATE, uid=uid)
    file_stat = os.fstat(descriptor)
    if (
        not stat.S_ISREG(file_stat.st_mode)
        or file_stat.st_uid != 0
        or stat.S_IMODE(file_stat.st_mode) != _LEASE_MODE
    ):
        os.close(descriptor)
        message = f"sandbox lease file must be root-owned mode-0600: {path}"
        raise SandboxLeaseError(message)
    return descriptor, path


@contextmanager
def _exclusive_directory_lock(directory: Path) -> Generator[None]:
    with ExitStack() as cleanup:
        descriptor = os.open(
            directory,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
        )
        cleanup.callback(os.close, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        cleanup.callback(fcntl.flock, descriptor, fcntl.LOCK_UN)
        yield


def _read_state(descriptor: int, *, uid: int) -> str:
    _ = os.lseek(descriptor, 0, os.SEEK_SET)
    payload = os.read(descriptor, 128).decode("ascii", errors="strict").strip()
    fields = payload.split()
    valid = (
        len(fields) == _LEASE_FIELD_COUNT
        and fields[0] in {_ACTIVE_STATE, _CLEAN_STATE}
        and fields[1].isdigit()
        and int(fields[1]) == uid
    )
    if not valid:
        message = "sandbox UID lease metadata is invalid"
        raise SandboxLeaseError(message)
    return fields[0]


def _write_state(descriptor: int, *, state: str, uid: int) -> None:
    payload = f"{state} {uid}\n".encode("ascii")
    _ = os.lseek(descriptor, 0, os.SEEK_SET)
    os.ftruncate(descriptor, 0)
    _ = os.write(descriptor, payload)
    os.fsync(descriptor)


def try_acquire_uid_lease(
    uid: int,
    *,
    allow_stale: bool = False,
    allow_live_owner: bool = False,
) -> SandboxUidLease | None:
    """Try to lock one UID, rejecting live owners and dirty crash state.

    Returns:
        A held lease, or ``None`` when this UID is unavailable or quarantined.

    Raises:
        OSError: If the kernel lease or process inspection operation fails.
        RuntimeError: If pidfd inspection is unsupported or lease metadata is invalid.
        UnicodeError: If persisted lease metadata is not strict ASCII.
    """
    descriptor, path = _open_lease_file(uid)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        return None
    try:
        activated = _activate_lease(
            descriptor,
            uid=uid,
            allow_stale=allow_stale,
            allow_live_owner=allow_live_owner,
        )
    except (OSError, RuntimeError, UnicodeError):
        _unlock_and_close(descriptor)
        raise
    if not activated:
        _unlock_and_close(descriptor)
        return None
    return SandboxUidLease(uid=uid, descriptor=descriptor, path=path)


def _activate_lease(
    descriptor: int,
    *,
    uid: int,
    allow_stale: bool,
    allow_live_owner: bool,
) -> bool:
    unavailable = _lease_is_unavailable(
        descriptor,
        uid=uid,
        allow_stale=allow_stale,
        allow_live_owner=allow_live_owner,
    )
    if unavailable:
        return False
    _write_state(descriptor, state=_ACTIVE_STATE, uid=uid)
    return True


def _unlock_and_close(descriptor: int) -> None:
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)


def _lease_is_unavailable(
    descriptor: int,
    *,
    uid: int,
    allow_stale: bool,
    allow_live_owner: bool,
) -> bool:
    state = _read_state(descriptor, uid=uid)
    live_owner = uid_has_live_processes(uid)
    return (live_owner and not allow_live_owner) or (
        state == _ACTIVE_STATE and not allow_stale
    )


def acquire_uid_lease(uid_range: range) -> SandboxUidLease:
    """Acquire the first cross-process-safe UID in the requested trust pool.

    Returns:
        The first clean, unlocked UID lease in the requested range.

    Raises:
        SandboxLeaseError: If no UID in the pool can be leased safely.
    """
    for uid in uid_range:
        lease = try_acquire_uid_lease(uid)
        if lease is not None:
            return lease
    message = "no submitted-code sandbox UID is available"
    raise SandboxLeaseError(message)


def release_uid_lease(lease: SandboxUidLease) -> None:
    """Persist a clean lifecycle before unlocking a reusable UID."""
    try:
        _mark_clean_and_unlock(lease)
    finally:
        os.close(lease.descriptor)


def _mark_clean_and_unlock(lease: SandboxUidLease) -> None:
    _write_state(lease.descriptor, state=_CLEAN_STATE, uid=lease.uid)
    fcntl.flock(lease.descriptor, fcntl.LOCK_UN)
