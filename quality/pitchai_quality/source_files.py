# Copyright (c) 2026 PitchAI. All rights reserved.
"""Discover the repository's complete first-party Python source surface."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from pitchai_quality.strict_policy import EXPECTED_NON_SOURCE_DIRECTORIES

if TYPE_CHECKING:
    from collections.abc import Iterable

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PYTHON_SUFFIXES = frozenset({".py", ".pyi"})
RUNTIME_PYTHON_SUFFIXES = frozenset({".py"})
NON_SOURCE_DIRECTORY_NAMES = EXPECTED_NON_SOURCE_DIRECTORIES
_GIT_SYMLINK_MODE = "120000"
_INDEX_RECORD_FIELD_COUNT = 2
_STANDARD_OUTPUT = 1
_STAGE_METADATA_FIELD_COUNT = 3

type _TrackedEntry = tuple[str, Path]


def _git_index_bytes(root: Path) -> bytes:
    read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
    with os.fdopen(read_fd, "rb") as stdout, os.fdopen(write_fd, "wb") as child_stdout:
        command = ("git", "-C", str(root), "ls-files", "--stage", "-z")
        environment_names = (name for name in os.environ if not name.startswith("GIT_"))
        environment = {name: os.environ[name] for name in environment_names}
        file_actions = (
            (os.POSIX_SPAWN_DUP2, child_stdout.fileno(), _STANDARD_OUTPUT),
            (os.POSIX_SPAWN_CLOSE, stdout.fileno()),
            (os.POSIX_SPAWN_CLOSE, child_stdout.fileno()),
        )
        pid = os.posix_spawnp(
            command[0],
            command,
            environment,
            file_actions=file_actions,
        )
        child_stdout.close()
        output = stdout.read()
    _completed_pid, status = os.waitpid(pid, 0)
    return_code = os.waitstatus_to_exitcode(status)
    if return_code != 0:
        message = f"git ls-files failed with status {return_code}"
        raise RuntimeError(message)
    return output


def _tracked_entries(root: Path) -> tuple[_TrackedEntry, ...]:
    entries: list[_TrackedEntry] = []
    for record in _git_index_bytes(root).split(b"\0"):
        if not record:
            continue
        parts = record.split(b"\t", maxsplit=1)
        if len(parts) != _INDEX_RECORD_FIELD_COUNT:
            message = "git ls-files emitted a malformed index record"
            raise RuntimeError(message)
        metadata, raw_path = parts
        fields = metadata.split(b" ")
        if len(fields) != _STAGE_METADATA_FIELD_COUNT:
            message = "git ls-files emitted malformed stage metadata"
            raise RuntimeError(message)
        relative = Path(os.fsdecode(raw_path))
        if relative.is_absolute() or ".." in relative.parts:
            message = f"git ls-files emitted an unsafe tracked path: {relative}"
            raise RuntimeError(message)
        entries.append((fields[0].decode("ascii"), relative))
    return tuple(entries)


def validate_tracked_source_topology(root: Path) -> None:
    """Reject tracked paths that can hide Python from complete-source discovery.

    Raises:
        RuntimeError: If Git metadata is invalid or a tracked path can bypass discovery.

    """
    violations: list[str] = []
    for mode, relative in _tracked_entries(root.resolve(strict=True)):
        if mode == _GIT_SYMLINK_MODE:
            violations.append(f"tracked symlink is forbidden in source topology: {relative.as_posix()}")
            continue
        excluded = NON_SOURCE_DIRECTORY_NAMES.intersection(relative.parts)
        if relative.suffix in PYTHON_SUFFIXES and excluded:
            violations.append(
                f"tracked Python source is hidden by an excluded directory: {relative.as_posix()}",
            )
    if violations:
        message = "invalid tracked source topology:\n- " + "\n- ".join(violations)
        raise RuntimeError(message)


def is_repository_source(
    path: Path,
    *,
    suffixes: frozenset[str] = PYTHON_SUFFIXES,
    repository_root: Path = REPOSITORY_ROOT,
) -> bool:
    """Return whether a file belongs to the checked first-party source surface."""
    resolved = path.resolve(strict=False)
    relative_parts = (
        resolved.relative_to(repository_root).parts if resolved.is_relative_to(repository_root) else resolved.parts
    )
    is_source_file = resolved.is_file() and resolved.suffix in suffixes
    return is_source_file and not NON_SOURCE_DIRECTORY_NAMES.intersection(relative_parts)


def iter_python_files(
    paths: Iterable[Path],
    *,
    suffixes: frozenset[str] = PYTHON_SUFFIXES,
    repository_root: Path = REPOSITORY_ROOT,
) -> tuple[Path, ...]:
    """Return every unique checked Python file below files or directories."""
    resolved_root = repository_root.resolve(strict=True)
    validate_tracked_source_topology(resolved_root)
    discovered: list[Path] = []
    for path in paths:
        resolved = path.resolve(strict=False)
        if is_repository_source(resolved, suffixes=suffixes, repository_root=resolved_root):
            discovered.append(resolved)
            continue
        if not resolved.is_dir():
            continue
        descendants = resolved.rglob("*")
        candidates = (candidate for candidate in descendants if candidate.suffix in suffixes)
        source_candidates = (
            candidate
            for candidate in candidates
            if is_repository_source(candidate, suffixes=suffixes, repository_root=resolved_root)
        )
        discovered.extend(source_candidates)
    return tuple(dict.fromkeys(sorted(discovered)))
