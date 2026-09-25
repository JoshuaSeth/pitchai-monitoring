# Copyright (c) 2026 PitchAI. All rights reserved.
"""Operating-system identity boundary for submitted code processes."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from e2e_runner.process_identity import kill_process_handle, owned_process_handles
from e2e_runner.runtime_alias import (
    SandboxRuntimeAliasError,
    prepare_runtime_alias,
    remove_runtime_alias,
    runtime_alias_path,
)
from e2e_runner.storage import validate_prepared_run_directory, validate_staged_source
from e2e_runner.uid_lease_config import SandboxLeaseError
from e2e_runner.uid_leases import acquire_uid_lease, release_uid_lease

if TYPE_CHECKING:
    from e2e_runner.process_identity import ProcessHandle
    from e2e_runner.uid_leases import SandboxUidLease

TRUSTED_UID_RANGE = range(55_000, 56_000)
UNTRUSTED_UID_RANGE = range(60_000, 65_000)
_SANDBOX_GID = 65_534
_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600
_READ_ONLY_SOURCE_MODE = 0o400
_PRIVATE_UMASK = 0o077
_TERMINATION_PASSES = 4


class SandboxIsolationError(RuntimeError):
    """Raised when the runner cannot establish its required OS boundary."""


@dataclass(frozen=True)
class SandboxIdentity:
    """Unique Unix identity and private filesystem roots for one code job."""

    uid: int
    gid: int
    umask: int
    trusted: bool
    home_directory: Path
    temporary_directory: Path
    uid_lease: SandboxUidLease

    @property
    def temporary_alias(self) -> Path:
        """Return the root-controlled short TMPDIR alias for this leased UID."""
        return runtime_alias_path(self.uid)


def acquire_submission_identity(
    *,
    artifacts_directory: Path,
    trusted_credentials: dict[str, str],
) -> SandboxIdentity:
    """Lease a unique active UID from the trusted or untrusted pool.

    Returns:
        The leased identity and its private job directories.

    Raises:
        SandboxIsolationError: If the selected UID pool has no free identity.
    """
    trusted = bool(trusted_credentials)
    uid_range = TRUSTED_UID_RANGE if trusted else UNTRUSTED_UID_RANGE
    try:
        lease = acquire_uid_lease(uid_range)
    except SandboxLeaseError as exc:
        raise SandboxIsolationError(str(exc)) from exc
    return SandboxIdentity(
        uid=lease.uid,
        gid=_SANDBOX_GID,
        umask=_PRIVATE_UMASK,
        trusted=trusted,
        home_directory=artifacts_directory / "sandbox-home",
        temporary_directory=artifacts_directory / "sandbox-tmp",
        uid_lease=lease,
    )


def release_submission_identity(identity: SandboxIdentity) -> None:
    """Return a sealed job's UID to its isolated trust-class pool.

    Raises:
        SandboxIsolationError: If the identity does not own its attached lease.
    """
    if identity.uid_lease.uid != identity.uid:
        message = "sandbox identity UID does not match its held lease"
        raise SandboxIsolationError(message)
    remove_runtime_alias(
        uid=identity.uid,
        expected_target=identity.temporary_directory,
    )
    release_uid_lease(identity.uid_lease)


def prepare_submission_filesystem(
    *,
    artifacts_directory: Path,
    staged_source: Path,
    identity: SandboxIdentity,
) -> None:
    """Give one non-root sandbox access only to its staged source and output root.

    Raises:
        SandboxIsolationError: If the supervisor lacks root identity-management privileges.
        SandboxRuntimeAliasError: If the short runtime path cannot be secured.
    """
    if os.geteuid() != 0:
        message = (
            "submitted code execution requires a root runner that can drop "
            "to a dedicated sandbox UID"
        )
        raise SandboxIsolationError(message)
    validate_prepared_run_directory(artifacts_directory)
    validate_staged_source(staged_source, run_directory=artifacts_directory)
    try:
        _create_identity_directories(identity)
    except FileExistsError as exc:
        message = "sandbox HOME or TMP path already exists before execution"
        raise SandboxIsolationError(message) from exc
    for directory in (
        artifacts_directory,
        identity.home_directory,
        identity.temporary_directory,
    ):
        os.chown(directory, identity.uid, identity.gid)
        directory.chmod(_PRIVATE_DIRECTORY_MODE)
    temporary_alias = prepare_runtime_alias(
        uid=identity.uid,
        target_directory=identity.temporary_directory,
    )
    if temporary_alias != identity.temporary_alias:
        message = "sandbox runtime alias changed after identity acquisition"
        raise SandboxRuntimeAliasError(message)
    os.chown(staged_source, identity.uid, identity.gid)
    staged_source.chmod(_READ_ONLY_SOURCE_MODE)


def _create_identity_directories(identity: SandboxIdentity) -> None:
    identity.home_directory.mkdir(mode=_PRIVATE_DIRECTORY_MODE)
    identity.temporary_directory.mkdir(mode=_PRIVATE_DIRECTORY_MODE)


async def terminate_identity_processes(identity: SandboxIdentity) -> None:
    """Kill descendants that escaped their original process group."""
    await terminate_uid_processes(identity.uid)


async def _kill_owned_process(handle: ProcessHandle) -> None:
    try:
        await asyncio.to_thread(kill_process_handle, handle)
    except ProcessLookupError:
        return


async def terminate_uid_processes(uid: int) -> None:
    """Kill every process owned by one dedicated sandbox UID through pidfds.

    Raises:
        SandboxIsolationError: If live processes survive every bounded kill pass.
    """
    for _pass_number in range(_TERMINATION_PASSES):
        handles = await owned_process_handles(uid)
        if not handles:
            return
        async with asyncio.TaskGroup() as task_group:
            for handle in handles:
                _ = task_group.create_task(_kill_owned_process(handle))
        await asyncio.sleep(0)
    remaining_handles = await owned_process_handles(uid)
    if remaining_handles:
        remaining_pids = [handle.pid for handle in remaining_handles]
        for handle in remaining_handles:
            os.close(handle.descriptor)
        message = (
            f"sandbox UID still owns live processes after termination: {uid}; "
            f"pids={remaining_pids}"
        )
        raise SandboxIsolationError(message)


def seal_submission_filesystem(artifacts_directory: Path) -> None:
    """Return a completed tree to root before its leased UID can be reused."""
    if not artifacts_directory.exists():
        return
    for root, directory_names, file_names in os.walk(
        artifacts_directory,
        topdown=False,
    ):
        root_path = Path(root)
        for name in file_names:
            seal_path(root_path / name, mode=_PRIVATE_FILE_MODE)
        for name in directory_names:
            seal_path(root_path / name, mode=_PRIVATE_DIRECTORY_MODE)
    seal_path(artifacts_directory, mode=_PRIVATE_DIRECTORY_MODE)


def seal_path(path: Path, *, mode: int) -> None:
    """Seal one path without following a submission-created symbolic link."""
    os.lchown(path, 0, 0)
    if not path.is_symlink():
        path.chmod(mode)
