# Copyright (c) 2026 PitchAI. All rights reserved.
"""Filesystem-contract probes for submitted-code staging and persisted volumes."""

from __future__ import annotations

import asyncio
import json
import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from e2e_registry.storage_permissions import migrate_registry_storage, validate_migrated_storage
from e2e_registry.testing import require_test_condition
from e2e_runner.code_execution import build_sandbox_environment
from e2e_runner.isolation import acquire_submission_identity, prepare_submission_filesystem
from e2e_runner.storage import prepare_job_directory
from tests.e2e_runner_isolation_support import (
    PRIVATE_DIRECTORY_MODE,
    PRIVATE_FILE_MODE,
    READABLE_SCRIPT,
    SYSTEM_PYTHON,
    TRAVERSABLE_DIRECTORY_MODE,
    PreparedIdentity,
    cleanup_prepared,
    launch_child,
    traversable_root,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_STORAGE_PROBE = READABLE_SCRIPT + """
import json
import os
from pathlib import Path
import sys

own_output = Path(os.environ["ARTIFACTS_DIR"]) / "probe-output.txt"
own_output.write_text("ok", encoding="utf-8")
print(json.dumps({
    "database": readable(sys.argv[1]),
    "registered_source": readable(sys.argv[2]),
    "historical_artifact": readable(sys.argv[3]),
    "own_source": readable(sys.argv[4]),
    "world_readable_host_file": readable("/etc/hosts"),
    "own_output": own_output.read_text(encoding="utf-8"),
}))
"""


@dataclass(frozen=True)
class StorageProbePaths:
    """Persisted and active paths inspected by one dropped-UID probe."""

    database: Path
    registered_source: Path
    historical_artifact: Path
    staged_source: Path


@pytest.fixture(name="storage_root")
def provide_storage_root() -> Iterator[Path]:
    """Provide a production-shaped top-level root for storage probes.

    Yields:
        A temporary root whose data and artifact children model separate mounts.
    """
    with traversable_root("pitchai-e2e-storage-") as root:
        yield root


def _write_world_readable(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(0o644)


async def _probe_storage_access(
    prepared: PreparedIdentity,
    environment: dict[str, str],
    paths: StorageProbePaths,
) -> None:
    capture = await launch_child(
        prepared,
        [
            SYSTEM_PYTHON,
            "-c",
            _STORAGE_PROBE,
            str(paths.database),
            str(paths.registered_source),
            str(paths.historical_artifact),
            str(paths.staged_source),
        ],
        environment,
        deadline_seconds=3.0,
    )
    record = cast("dict[str, object]", json.loads(capture.stdout))
    require_test_condition(
        condition=record["database"] is False,
        message="registry DB must be unreadable",
    )
    require_test_condition(
        condition=record["registered_source"] is False,
        message="registered source volume must be unreadable",
    )
    require_test_condition(
        condition=record["historical_artifact"] is False,
        message="completed run artifacts must be unreadable",
    )
    require_test_condition(
        condition=record["own_source"] is True,
        message="staged source must be readable",
    )
    require_test_condition(
        condition=record["own_output"] == "ok",
        message="active output root must be writable",
    )
    require_test_condition(
        condition=record["world_readable_host_file"] is True,
        message="UID isolation is not a filesystem namespace and must not be represented as one",
    )


@pytest.mark.asyncio
async def test_migration_denies_persisted_volumes_but_keeps_active_job_private(storage_root: Path) -> None:
    """A dropped job may use its run root but not registry, source, or historical data."""
    data_root = storage_root / "data"
    tests_directory = data_root / "e2e-tests"
    database_path = data_root / "e2e-registry.db"
    registered_source = tests_directory / "tenant" / "source.py"
    artifacts_directory = storage_root / "artifacts"
    historical_artifact = artifacts_directory / "old-tenant" / "old-test" / "old-run" / "history.log"
    _write_world_readable(database_path, b"registry")
    _write_world_readable(registered_source, b"source")
    _write_world_readable(historical_artifact, b"history")

    await asyncio.to_thread(
        migrate_registry_storage,
        database_path=database_path,
        tests_directory=tests_directory,
        artifacts_directory=artifacts_directory,
    )
    await asyncio.to_thread(
        validate_migrated_storage,
        tests_directory=tests_directory,
        artifacts_directory=artifacts_directory,
    )
    run_directory = await asyncio.to_thread(
        prepare_job_directory,
        artifacts_root=artifacts_directory,
        tenant_id="active-tenant",
        test_id="active-test",
        run_id="active-run",
    )
    staged_source = run_directory / "verified_source.py"
    staged_source.write_text("# verified\n", encoding="utf-8")
    staged_source.chmod(PRIVATE_FILE_MODE)
    identity = acquire_submission_identity(artifacts_directory=run_directory, trusted_credentials={})
    await asyncio.to_thread(
        prepare_submission_filesystem,
        artifacts_directory=run_directory,
        staged_source=staged_source,
        identity=identity,
    )
    prepared = PreparedIdentity(identity, run_directory, staged_source)
    environment = build_sandbox_environment(
        base_url="https://target.invalid",
        artifacts_dir=run_directory,
        identity=identity,
    )
    try:
        await _probe_storage_access(
            prepared,
            environment,
            StorageProbePaths(
                database_path,
                registered_source,
                historical_artifact,
                staged_source,
            ),
        )
    finally:
        await cleanup_prepared(prepared)

    require_test_condition(
        condition=stat.S_IMODE(data_root.stat().st_mode) == PRIVATE_DIRECTORY_MODE,
        message="the data mount root must be mode 0700",
    )
    require_test_condition(
        condition=stat.S_IMODE((historical_artifact.parent.parent.parent).stat().st_mode)
        == TRAVERSABLE_DIRECTORY_MODE,
        message="tenant artifact directories must be traversal-only",
    )
    require_test_condition(
        condition=stat.S_IMODE(historical_artifact.parent.stat().st_mode) == PRIVATE_DIRECTORY_MODE,
        message="completed run roots must be mode 0700",
    )
    require_test_condition(
        condition=stat.S_IMODE(historical_artifact.stat().st_mode) == PRIVATE_FILE_MODE,
        message="completed artifact files must be mode 0600",
    )
