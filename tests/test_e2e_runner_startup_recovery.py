# Copyright (c) 2026 PitchAI. All rights reserved.
"""Crash-recovery probes for persisted sandbox identities and artifacts."""

from __future__ import annotations

import asyncio
import multiprocessing
import os
import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from e2e_registry.storage_permissions import migrate_registry_storage
from e2e_registry.storage_recovery import inspect_post_marker_artifacts
from e2e_registry.testing import require_test_condition
from e2e_runner import runtime_alias
from e2e_runner.isolation import (
    acquire_submission_identity,
    prepare_submission_filesystem,
    terminate_uid_processes,
)
from e2e_runner.recovery import recover_interrupted_submissions
from e2e_runner.storage import prepare_job_directory, write_new_private_file
from e2e_runner.uid_lease_config import LEASE_DIRECTORY_ENVIRONMENT
from e2e_runner.uid_leases import release_uid_lease, try_acquire_uid_lease
from tests.e2e_runner_lease_process_support import hold_sandbox_uid

if TYPE_CHECKING:
    from multiprocessing.process import BaseProcess
    from multiprocessing.synchronize import Event
    from pathlib import Path

    from e2e_runner.isolation import SandboxIdentity

_PROCESS_JOIN_SECONDS = 10
_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600


@dataclass(frozen=True)
class MigratedStorage:
    """Private test storage paths after the one-time migration."""

    artifacts_directory: Path
    tests_directory: Path


@dataclass(frozen=True)
class RecoveryRun:
    """Paths participating in one interrupted-run recovery probe."""

    artifacts_directory: Path
    run_directory: Path
    staged_source: Path


def _prepare_migrated_storage(root: Path) -> MigratedStorage:
    data_directory = root / "data"
    tests_directory = data_directory / "tests"
    artifacts_directory = root / "artifacts"
    tests_directory.mkdir(parents=True)
    artifacts_directory.mkdir()
    database_path = data_directory / "e2e-registry.db"
    _ = database_path.write_bytes(b"test database")
    migrate_registry_storage(
        database_path=database_path,
        tests_directory=tests_directory,
        artifacts_directory=artifacts_directory,
    )
    return MigratedStorage(artifacts_directory, tests_directory)


def _prepare_run(artifacts_directory: Path, *, run_id: str) -> RecoveryRun:
    run_directory = prepare_job_directory(
        artifacts_root=artifacts_directory,
        tenant_id="tenant",
        test_id="test",
        run_id=run_id,
    )
    staged_source = run_directory / "verified_source.py"
    write_new_private_file(staged_source, b"print('probe')\n")
    return RecoveryRun(artifacts_directory, run_directory, staged_source)


async def _verify_startup_recovery(
    process: BaseProcess,
    ready: Event,
    identity: SandboxIdentity,
    recovery_run: RecoveryRun,
) -> None:
    ready_is_set = await asyncio.to_thread(ready.wait, _PROCESS_JOIN_SECONDS)
    require_test_condition(condition=ready_is_set, message="orphan process must become ready")
    os.close(identity.uid_lease.descriptor)
    await recover_interrupted_submissions(recovery_run.artifacts_directory)
    await asyncio.to_thread(process.join, _PROCESS_JOIN_SECONDS)
    require_test_condition(
        condition=not process.is_alive(),
        message="startup must kill the orphan UID owner",
    )
    run_stat, source_stat = await asyncio.gather(
        asyncio.to_thread(recovery_run.run_directory.stat),
        asyncio.to_thread(recovery_run.staged_source.stat),
    )
    require_test_condition(
        condition=run_stat.st_uid == 0
        and stat.S_IMODE(run_stat.st_mode) == _PRIVATE_DIRECTORY_MODE,
        message="recovered run roots must be root-owned mode 0700",
    )
    require_test_condition(
        condition=source_stat.st_uid == 0
        and stat.S_IMODE(source_stat.st_mode) == _PRIVATE_FILE_MODE,
        message="recovered run files must be root-owned mode 0600",
    )
    require_test_condition(
        condition=not identity.temporary_alias.is_symlink(),
        message="startup recovery must remove the interrupted UID's exact runtime alias",
    )
    reused_lease = try_acquire_uid_lease(identity.uid)
    require_test_condition(
        condition=reused_lease is not None,
        message="recovered UID must become reusable",
    )
    if reused_lease is not None:
        release_uid_lease(reused_lease)


def test_post_marker_inspection_reseals_root_owned_completed_runs(tmp_path: Path) -> None:
    """Startup must repair permissive modes left on completed root-owned runs."""
    storage = _prepare_migrated_storage(tmp_path)
    recovery_run = _prepare_run(storage.artifacts_directory, run_id="completed")
    recovery_run.run_directory.chmod(0o777)
    recovery_run.staged_source.chmod(0o666)

    interrupted_uids = inspect_post_marker_artifacts(storage.artifacts_directory)

    require_test_condition(
        condition=not interrupted_uids,
        message="root-owned runs must be completed",
    )
    require_test_condition(
        condition=(
            stat.S_IMODE(recovery_run.run_directory.stat().st_mode)
            == _PRIVATE_DIRECTORY_MODE
        ),
        message="completed run roots must be resealed mode 0700",
    )
    require_test_condition(
        condition=(
            stat.S_IMODE(recovery_run.staged_source.stat().st_mode)
            == _PRIVATE_FILE_MODE
        ),
        message="completed run files must be resealed mode 0600",
    )


@pytest.mark.asyncio
async def test_startup_recovers_crashed_uid_process_and_artifact_tree(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A crash-dirty UID is killed and sealed before it becomes reusable."""
    monkeypatch.setenv(LEASE_DIRECTORY_ENVIRONMENT, str(tmp_path / "leases"))
    monkeypatch.setattr(runtime_alias, "RUNTIME_ALIAS_ROOT", tmp_path / "runtime-aliases")
    storage = _prepare_migrated_storage(tmp_path)
    recovery_run = _prepare_run(storage.artifacts_directory, run_id="interrupted")
    identity = acquire_submission_identity(
        artifacts_directory=recovery_run.run_directory,
        trusted_credentials={},
    )
    prepare_submission_filesystem(
        artifacts_directory=recovery_run.run_directory,
        staged_source=recovery_run.staged_source,
        identity=identity,
    )
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    process = context.Process(target=hold_sandbox_uid, args=(identity.uid, ready))
    process.start()
    try:
        await _verify_startup_recovery(
            process,
            ready,
            identity,
            recovery_run,
        )
    finally:
        if process.is_alive():
            await terminate_uid_processes(identity.uid)
            await asyncio.to_thread(process.join, _PROCESS_JOIN_SECONDS)
