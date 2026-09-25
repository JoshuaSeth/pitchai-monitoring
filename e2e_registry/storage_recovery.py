# Copyright (c) 2026 PitchAI. All rights reserved.
"""Post-marker artifact ownership inspection and crash recovery."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from e2e_registry.storage_permissions import (
    ARTIFACT_TRAVERSAL_MODE,
    PRIVATE_DIRECTORY_MODE,
    PRIVATE_FILE_MODE,
    STORAGE_MIGRATION_MARKER,
    StoragePermissionError,
)


def _require_directory(path: Path) -> os.stat_result:
    try:
        path_stat = path.lstat()
    except FileNotFoundError as exc:
        message = f"artifact recovery path disappeared: {path}"
        raise StoragePermissionError(message) from exc
    if not stat.S_ISDIR(path_stat.st_mode) or stat.S_ISLNK(path_stat.st_mode):
        message = f"artifact recovery requires a non-linked directory: {path}"
        raise StoragePermissionError(message)
    return path_stat


def _seal_entry(path: Path, *, directory: bool) -> None:
    path_stat = path.lstat()
    expected = (
        stat.S_ISDIR(path_stat.st_mode)
        if directory
        else stat.S_ISREG(path_stat.st_mode)
    )
    if not expected or stat.S_ISLNK(path_stat.st_mode):
        message = f"artifact recovery rejects linked or special paths: {path}"
        raise StoragePermissionError(message)
    os.chown(path, 0, 0, follow_symlinks=False)
    path.chmod(PRIVATE_DIRECTORY_MODE if directory else PRIVATE_FILE_MODE)


def _seal_run_tree(run_directory: Path) -> None:
    for root, directory_names, file_names in os.walk(
        run_directory,
        topdown=False,
        followlinks=False,
    ):
        root_path = Path(root)
        for name in file_names:
            _seal_entry(root_path / name, directory=False)
        for name in directory_names:
            _seal_entry(root_path / name, directory=True)
    _seal_entry(run_directory, directory=True)


def inspect_post_marker_artifacts(artifacts_directory: Path) -> set[int]:
    """Seal completed runs and identify interrupted active runs.

    Returns:
        UIDs that still own an interrupted run directory.

    Raises:
        StoragePermissionError: If an artifact entry violates the storage contract.
    """
    interrupted_uids: set[int] = set()
    for tenant_directory in artifacts_directory.iterdir():
        if tenant_directory.name == STORAGE_MIGRATION_MARKER:
            continue
        tenant_stat = _require_directory(tenant_directory)
        if tenant_stat.st_uid != 0:
            message = f"artifact tenant directory is not root-owned: {tenant_directory}"
            raise StoragePermissionError(message)
        tenant_directory.chmod(ARTIFACT_TRAVERSAL_MODE)
        for test_directory in tenant_directory.iterdir():
            test_stat = _require_directory(test_directory)
            if test_stat.st_uid != 0:
                message = f"artifact test directory is not root-owned: {test_directory}"
                raise StoragePermissionError(message)
            test_directory.chmod(ARTIFACT_TRAVERSAL_MODE)
            for run_directory in test_directory.iterdir():
                run_stat = _require_directory(run_directory)
                if run_stat.st_uid == 0:
                    _seal_run_tree(run_directory)
                else:
                    interrupted_uids.add(run_stat.st_uid)
    return interrupted_uids


def seal_artifact_runs_for_uid(artifacts_directory: Path, *, uid: int) -> None:
    """Seal every interrupted run root owned by one recovered sandbox UID."""
    for tenant_directory in artifacts_directory.iterdir():
        if tenant_directory.name == STORAGE_MIGRATION_MARKER:
            continue
        _ = _require_directory(tenant_directory)
        for test_directory in tenant_directory.iterdir():
            _ = _require_directory(test_directory)
            for run_directory in test_directory.iterdir():
                run_stat = _require_directory(run_directory)
                if run_stat.st_uid == uid:
                    _seal_run_tree(run_directory)
