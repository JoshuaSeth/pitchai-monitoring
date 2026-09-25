# Copyright (c) 2026 PitchAI. All rights reserved.
"""Fail-closed artifact paths and private supervisor file operations."""

from __future__ import annotations

import os
import re
import stat
from contextlib import ExitStack
from pathlib import Path

ARTIFACT_ROOT_MODE = 0o711
ARTIFACT_TRAVERSAL_MODE = 0o711
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
_COMPONENT_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_PRIVATE_FILE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW


class ArtifactStorageError(RuntimeError):
    """Raised when runner storage does not meet its no-follow contract."""


def validate_storage_component(value: str, *, label: str) -> str:
    """Return a safe single path component or fail before filesystem access.

    Raises:
        ArtifactStorageError: If the value is empty, nested, or unsupported.
    """
    component = str(value or "").strip()
    if _COMPONENT_PATTERN.fullmatch(component) is None or component in {".", ".."}:
        message = f"unsafe {label} storage component"
        raise ArtifactStorageError(message)
    return component


def _require_root_supervisor() -> None:
    if os.geteuid() != 0:
        message = "artifact storage preparation requires a root runner supervisor"
        raise ArtifactStorageError(message)


def _require_directory_stat(file_stat: os.stat_result, *, mode: int, label: str) -> None:
    actual_mode = stat.S_IMODE(file_stat.st_mode)
    if not stat.S_ISDIR(file_stat.st_mode) or file_stat.st_uid != 0 or actual_mode != mode:
        message = f"{label} must be a root-owned mode-{mode:04o} directory"
        raise ArtifactStorageError(message)


def validate_no_symlink_path(path: Path) -> None:
    """Reject any existing symbolic-link component in a path.

    Raises:
        ArtifactStorageError: If an existing component is a symbolic link.
    """
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        try:
            file_stat = current.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(file_stat.st_mode):
            message = f"storage path contains a symbolic link: {current}"
            raise ArtifactStorageError(message)


def ensure_artifact_root(artifacts_root: Path) -> None:
    """Create an absent artifact root or validate the migrated root contract."""
    _require_root_supervisor()
    validate_no_symlink_path(artifacts_root)
    if not artifacts_root.exists():
        artifacts_root.mkdir(mode=ARTIFACT_ROOT_MODE, parents=True)
        os.chown(artifacts_root, 0, 0)
        artifacts_root.chmod(ARTIFACT_ROOT_MODE)
    _require_directory_stat(artifacts_root.lstat(), mode=ARTIFACT_ROOT_MODE, label="artifact root")


def _create_or_open_traversal_directory(parent_fd: int, component: str) -> int:
    try:
        os.mkdir(component, mode=ARTIFACT_TRAVERSAL_MODE, dir_fd=parent_fd)
    except FileExistsError:
        return os.open(component, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    return os.open(component, _DIRECTORY_FLAGS, dir_fd=parent_fd)


def _open_traversal_directory(parent_fd: int, component: str, *, label: str) -> int:
    child_fd = _create_or_open_traversal_directory(parent_fd, component)
    try:
        _require_directory_stat(os.fstat(child_fd), mode=ARTIFACT_TRAVERSAL_MODE, label=label)
    except (ArtifactStorageError, OSError):
        os.close(child_fd)
        raise
    return child_fd


def prepare_job_directory(
    *,
    artifacts_root: Path,
    tenant_id: str,
    test_id: str,
    run_id: str,
) -> Path:
    """Create one never-before-used private run directory without following links.

    Returns:
        The new root-owned mode-0700 run directory.

    Raises:
        ArtifactStorageError: If any component is unsafe, linked, reused, or misconfigured.
    """
    tenant = validate_storage_component(tenant_id, label="tenant_id")
    test = validate_storage_component(test_id, label="test_id")
    run = validate_storage_component(run_id, label="run_id")
    ensure_artifact_root(artifacts_root)
    with ExitStack() as descriptors:
        root_fd = os.open(artifacts_root, _DIRECTORY_FLAGS)
        descriptors.callback(os.close, root_fd)
        tenant_fd = _open_traversal_directory(root_fd, tenant, label="tenant artifact directory")
        descriptors.callback(os.close, tenant_fd)
        test_fd = _open_traversal_directory(tenant_fd, test, label="test artifact directory")
        descriptors.callback(os.close, test_fd)
        try:
            os.mkdir(run, mode=PRIVATE_DIRECTORY_MODE, dir_fd=test_fd)
        except FileExistsError as exc:
            message = f"artifact run directory already exists: {run}"
            raise ArtifactStorageError(message) from exc
        run_fd = os.open(run, _DIRECTORY_FLAGS, dir_fd=test_fd)
        descriptors.callback(os.close, run_fd)
        _require_directory_stat(os.fstat(run_fd), mode=PRIVATE_DIRECTORY_MODE, label="artifact run directory")
    return artifacts_root / tenant / test / run


def validate_prepared_run_directory(directory: Path) -> None:
    """Validate a prepared run root before privileged writes or ownership changes."""
    validate_no_symlink_path(directory)
    _require_directory_stat(directory.lstat(), mode=PRIVATE_DIRECTORY_MODE, label="artifact run directory")


def validate_staged_source(path: Path, *, run_directory: Path) -> None:
    """Require a direct, regular, private source snapshot before ownership changes.

    Raises:
        ArtifactStorageError: If the snapshot is nested, linked, reused, or permissive.
    """
    validate_prepared_run_directory(run_directory)
    if path.parent != run_directory:
        message = "staged source must be a direct child of its prepared run directory"
        raise ArtifactStorageError(message)
    validate_no_symlink_path(path)
    source_stat = path.lstat()
    actual_mode = stat.S_IMODE(source_stat.st_mode)
    if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_uid != 0 or actual_mode != PRIVATE_FILE_MODE:
        message = "staged source must be a root-owned mode-0600 regular file"
        raise ArtifactStorageError(message)


def prepare_staging_directory(directory: Path) -> None:
    """Create an exclusive private staging leaf for direct integrity callers.

    Raises:
        ArtifactStorageError: If the path is linked, reused, or cannot be prepared.
    """
    _require_root_supervisor()
    validate_no_symlink_path(directory)
    try:
        directory.mkdir(mode=PRIVATE_DIRECTORY_MODE)
    except FileExistsError as exc:
        message = f"source staging directory already exists: {directory}"
        raise ArtifactStorageError(message) from exc
    os.chown(directory, 0, 0)
    directory.chmod(PRIVATE_DIRECTORY_MODE)
    validate_prepared_run_directory(directory)


def write_new_private_file(path: Path, content: bytes) -> None:
    """Create a private file atomically and refuse an existing or linked target."""
    validate_prepared_run_directory(path.parent)
    with ExitStack() as descriptors:
        parent_fd = os.open(path.parent, _DIRECTORY_FLAGS)
        descriptors.callback(os.close, parent_fd)
        file_fd = os.open(path.name, _PRIVATE_FILE_FLAGS, PRIVATE_FILE_MODE, dir_fd=parent_fd)
        descriptors.callback(os.close, file_fd)
        with os.fdopen(file_fd, "wb", closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(file_fd)


def replace_private_file(path: Path, content: bytes) -> None:
    """Replace one supervisor-owned artifact without following an untrusted link."""
    validate_prepared_run_directory(path.parent)
    with ExitStack() as descriptors:
        parent_fd = os.open(path.parent, _DIRECTORY_FLAGS)
        descriptors.callback(os.close, parent_fd)
        _ = _unlink_if_present(parent_fd, path.name)
        file_fd = os.open(path.name, _PRIVATE_FILE_FLAGS, PRIVATE_FILE_MODE, dir_fd=parent_fd)
        descriptors.callback(os.close, file_fd)
        with os.fdopen(file_fd, "wb", closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(file_fd)


def _unlink_if_present(parent_fd: int, filename: str) -> bool:
    try:
        os.unlink(filename, dir_fd=parent_fd)
    except FileNotFoundError:
        return False
    return True
