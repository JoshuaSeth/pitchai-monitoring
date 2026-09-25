# Copyright (c) 2026 PitchAI. All rights reserved.
"""One-time private-volume migration and its persistent storage contract."""

from __future__ import annotations

import os
import stat
from pathlib import Path

DATA_ROOT_MODE = 0o700
SOURCE_DIRECTORY_MODE = 0o700
ARTIFACT_ROOT_MODE = 0o711
ARTIFACT_TRAVERSAL_MODE = 0o711
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
STORAGE_MIGRATION_MARKER = ".pitchai-private-storage-v1"
_MIGRATION_VERSION = b"pitchai-private-storage-v1\n"
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
_ARTIFACT_TRAVERSAL_DEPTH = 2


class StoragePermissionError(RuntimeError):
    """Raised when a mounted registry volume cannot be made private safely."""


def _require_root_supervisor() -> None:
    if os.geteuid() != 0:
        message = "registry storage migration requires a root supervisor"
        raise StoragePermissionError(message)


def _require_unlinked_path(path: Path) -> os.stat_result:
    try:
        file_stat = path.lstat()
    except FileNotFoundError as exc:
        message = f"required storage path is missing: {path}"
        raise StoragePermissionError(message) from exc
    if stat.S_ISLNK(file_stat.st_mode):
        message = f"storage contract rejects symbolic links: {path}"
        raise StoragePermissionError(message)
    return file_stat


def _seal_path(path: Path, *, mode: int, directory: bool) -> None:
    file_stat = _require_unlinked_path(path)
    expected_type = stat.S_ISDIR(file_stat.st_mode) if directory else stat.S_ISREG(file_stat.st_mode)
    if not expected_type:
        expected_label = "directory" if directory else "regular file"
        message = f"storage path must be a {expected_label}: {path}"
        raise StoragePermissionError(message)
    os.chown(path, 0, 0, follow_symlinks=False)
    path.chmod(mode)


def _require_owned_mode(path: Path, *, mode: int, directory: bool) -> None:
    file_stat = _require_unlinked_path(path)
    expected_type = stat.S_ISDIR(file_stat.st_mode) if directory else stat.S_ISREG(file_stat.st_mode)
    if not expected_type or file_stat.st_uid != 0 or stat.S_IMODE(file_stat.st_mode) != mode:
        expected_label = "directory" if directory else "regular file"
        message = f"storage path must be a root-owned mode-{mode:04o} {expected_label}: {path}"
        raise StoragePermissionError(message)


def _seal_source_tree(tests_directory: Path) -> None:
    _seal_path(tests_directory, mode=SOURCE_DIRECTORY_MODE, directory=True)
    for root, directory_names, file_names in os.walk(tests_directory, topdown=True, followlinks=False):
        root_path = Path(root)
        for name in directory_names:
            _seal_path(root_path / name, mode=SOURCE_DIRECTORY_MODE, directory=True)
        for name in file_names:
            _seal_path(root_path / name, mode=PRIVATE_FILE_MODE, directory=False)


def _artifact_directory_mode(artifacts_directory: Path, path: Path) -> int:
    depth = len(path.relative_to(artifacts_directory).parts)
    return ARTIFACT_TRAVERSAL_MODE if depth <= _ARTIFACT_TRAVERSAL_DEPTH else PRIVATE_DIRECTORY_MODE


def _seal_historical_artifacts(artifacts_directory: Path) -> None:
    for root, directory_names, file_names in os.walk(artifacts_directory, topdown=True, followlinks=False):
        root_path = Path(root)
        for name in directory_names:
            path = root_path / name
            _seal_path(path, mode=_artifact_directory_mode(artifacts_directory, path), directory=True)
        for name in file_names:
            path = root_path / name
            if path.name == STORAGE_MIGRATION_MARKER and path.parent == artifacts_directory:
                continue
            _seal_path(path, mode=PRIVATE_FILE_MODE, directory=False)


def _marker_is_valid(artifacts_directory: Path) -> bool:
    marker_path = artifacts_directory / STORAGE_MIGRATION_MARKER
    try:
        marker_path.lstat()
    except FileNotFoundError:
        return False
    marker_stat = _require_unlinked_path(marker_path)
    valid_metadata = (
        stat.S_ISREG(marker_stat.st_mode)
        and marker_stat.st_uid == 0
        and stat.S_IMODE(marker_stat.st_mode) == PRIVATE_FILE_MODE
    )
    if not valid_metadata or marker_path.read_bytes() != _MIGRATION_VERSION:
        message = "artifact storage migration marker is invalid"
        raise StoragePermissionError(message)
    return True


def _write_marker_contents(marker_fd: int) -> None:
    _ = os.write(marker_fd, _MIGRATION_VERSION)
    os.fsync(marker_fd)


def _create_marker_at(directory_fd: int) -> None:
    marker_fd = os.open(
        STORAGE_MIGRATION_MARKER,
        _FILE_CREATE_FLAGS,
        PRIVATE_FILE_MODE,
        dir_fd=directory_fd,
    )
    try:
        _write_marker_contents(marker_fd)
    finally:
        os.close(marker_fd)


def _write_migration_marker(artifacts_directory: Path) -> None:
    directory_fd = os.open(artifacts_directory, _DIRECTORY_FLAGS)
    try:
        _create_marker_at(directory_fd)
    finally:
        os.close(directory_fd)


def migrate_registry_storage(
    *,
    database_path: Path,
    tests_directory: Path,
    artifacts_directory: Path,
) -> None:
    """Converge persisted registry data and historical artifacts to private modes."""
    _require_root_supervisor()
    _seal_path(database_path.parent, mode=DATA_ROOT_MODE, directory=True)
    _seal_path(database_path, mode=PRIVATE_FILE_MODE, directory=False)
    _seal_source_tree(tests_directory)
    _seal_path(artifacts_directory, mode=ARTIFACT_ROOT_MODE, directory=True)
    if _marker_is_valid(artifacts_directory):
        return
    _seal_historical_artifacts(artifacts_directory)
    _write_migration_marker(artifacts_directory)


def validate_migrated_storage(*, tests_directory: Path, artifacts_directory: Path) -> None:
    """Fail a runner startup unless the registry completed the private migration.

    Raises:
        StoragePermissionError: If the private migration marker is absent or invalid.
    """
    _require_root_supervisor()
    _require_owned_mode(tests_directory.parent, mode=DATA_ROOT_MODE, directory=True)
    _require_owned_mode(tests_directory, mode=SOURCE_DIRECTORY_MODE, directory=True)
    _require_owned_mode(artifacts_directory, mode=ARTIFACT_ROOT_MODE, directory=True)
    if not _marker_is_valid(artifacts_directory):
        message = "runner artifact storage has not completed its private migration"
        raise StoragePermissionError(message)
