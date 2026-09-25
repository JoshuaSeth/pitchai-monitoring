# Copyright (c) 2026 PitchAI. All rights reserved.
"""Runner startup recovery for crash-interrupted sandbox identities."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from e2e_registry.storage_permissions import StoragePermissionError
from e2e_registry.storage_recovery import (
    inspect_post_marker_artifacts,
    seal_artifact_runs_for_uid,
)
from e2e_runner.isolation import (
    TRUSTED_UID_RANGE,
    UNTRUSTED_UID_RANGE,
    terminate_uid_processes,
)
from e2e_runner.runtime_alias import recorded_runtime_alias_uids, remove_runtime_alias
from e2e_runner.uid_leases import (
    recorded_lease_uids,
    release_uid_lease,
    try_acquire_uid_lease,
)

if TYPE_CHECKING:
    from pathlib import Path


async def recover_interrupted_submissions(artifacts_directory: Path) -> None:
    """Terminate and seal orphaned UID-owned runs before accepting new jobs.

    Raises:
        StoragePermissionError: If artifacts reference a UID outside both pools.
    """
    interrupted_uids = await asyncio.to_thread(
        inspect_post_marker_artifacts,
        artifacts_directory,
    )
    persisted_uids = await asyncio.to_thread(recorded_lease_uids)
    alias_uids = await asyncio.to_thread(recorded_runtime_alias_uids)
    for uid in interrupted_uids | persisted_uids | alias_uids:
        sandbox_uid = uid in TRUSTED_UID_RANGE or uid in UNTRUSTED_UID_RANGE
        if not sandbox_uid:
            message = f"artifact run is owned by an unexpected UID: {uid}"
            raise StoragePermissionError(message)
        lease = await asyncio.to_thread(
            try_acquire_uid_lease,
            uid,
            allow_stale=True,
            allow_live_owner=True,
        )
        if lease is None:
            continue
        await _recover_uid(artifacts_directory, uid=uid)
        release_uid_lease(lease)


async def _recover_uid(artifacts_directory: Path, *, uid: int) -> None:
    await terminate_uid_processes(uid)
    await asyncio.to_thread(
        seal_artifact_runs_for_uid,
        artifacts_directory,
        uid=uid,
    )
    await asyncio.to_thread(
        remove_runtime_alias,
        uid=uid,
        artifacts_root=artifacts_directory,
    )
