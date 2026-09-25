# Copyright (c) 2026 PitchAI. All rights reserved.
"""Fail-closed path-hardening contracts for submitted E2E jobs."""

from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING

import pytest

from e2e_registry.testing import require_test_condition
from e2e_runner.integrity import SourceIntegrityFailure, stage_verified_source
from e2e_runner.storage import ArtifactStorageError, prepare_job_directory
from tests.e2e_runner_isolation_support import (
    TRAVERSABLE_DIRECTORY_MODE,
    traversable_root,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(name="storage_root")
def provide_storage_root() -> Iterator[Path]:
    """Provide a traversal-only root for privileged path probes.

    Yields:
        A temporary directory that resembles the artifact mount.
    """
    with traversable_root("pitchai-e2e-paths-") as root:
        yield root


def _write_world_readable(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(0o644)


@pytest.mark.asyncio
async def test_staging_refuses_reused_symlink_target_without_overwrite(storage_root: Path) -> None:
    """Verified bytes must never follow a pre-positioned source symlink."""
    tests_directory = storage_root / "tests"
    source = tests_directory / "source.py"
    _write_world_readable(source, b"print('verified')\n")
    artifacts = storage_root / "artifacts"
    artifacts.mkdir(mode=TRAVERSABLE_DIRECTORY_MODE)
    os.chown(artifacts, 0, 0)
    run_directory = prepare_job_directory(
        artifacts_root=artifacts,
        tenant_id="tenant",
        test_id="test",
        run_id="run",
    )
    protected_target = storage_root / "protected.txt"
    protected_target.write_bytes(b"do-not-overwrite")
    (run_directory / "verified_source.py").symlink_to(protected_target)

    outcome = await stage_verified_source(
        tests_dir=tests_directory,
        source_relpath="source.py",
        expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        staging_dir=run_directory,
        prepared_staging_directory=True,
    )

    require_test_condition(
        condition=isinstance(outcome, SourceIntegrityFailure),
        message="a pre-positioned staging link must fail closed",
    )
    require_test_condition(
        condition=protected_target.read_bytes() == b"do-not-overwrite",
        message="staging must not overwrite a symbolic-link target",
    )


def test_job_directory_rejects_unsafe_reused_and_linked_components(storage_root: Path) -> None:
    """Untrusted job identifiers and pre-existing run roots must never be reused."""
    artifacts = storage_root / "artifacts"
    artifacts.mkdir(mode=TRAVERSABLE_DIRECTORY_MODE)
    os.chown(artifacts, 0, 0)
    with pytest.raises(ArtifactStorageError, match="unsafe tenant_id"):
        prepare_job_directory(
            artifacts_root=artifacts,
            tenant_id="../escape",
            test_id="test",
            run_id="run",
        )
    run_directory = prepare_job_directory(
        artifacts_root=artifacts,
        tenant_id="tenant",
        test_id="test",
        run_id="run",
    )
    with pytest.raises(ArtifactStorageError, match="already exists"):
        prepare_job_directory(
            artifacts_root=artifacts,
            tenant_id="tenant",
            test_id="test",
            run_id="run",
        )
    run_directory.rmdir()
    run_directory.symlink_to(storage_root / "linked-target", target_is_directory=True)
    with pytest.raises(ArtifactStorageError, match="already exists"):
        prepare_job_directory(
            artifacts_root=artifacts,
            tenant_id="tenant",
            test_id="test",
            run_id="run",
        )
