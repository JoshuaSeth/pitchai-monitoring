# Copyright (c) 2026 PitchAI. All rights reserved.
"""Refuse unsafe or unrelated journal allocations without changing them."""

from __future__ import annotations

import os
import sqlite3
import stat
from contextlib import ExitStack, closing, suppress
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pathlib import Path

_PRIVATE_DIRECTORY = 0o700
_PRIVATE_FILE = 0o600
_APPLICATION_ID = 0x4446544A
_SCHEMA_VERSION = 1


def _validate_parent(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts or any(parent.is_symlink() for parent in path.parents):
        message = "dft_journal_unsafe_path"
        raise ValueError(message)
    parent = path.parent.stat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid() or (
        stat.S_IMODE(parent.st_mode) != _PRIVATE_DIRECTORY
    ):
        message = "dft_journal_unsafe_parent"
        raise ValueError(message)


def _validate_file(info: os.stat_result) -> None:
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or (
        stat.S_IMODE(info.st_mode) != _PRIVATE_FILE
    ):
        message = "dft_journal_unsafe_file"
        raise ValueError(message)


def _prepare_file(path: Path) -> bool:
    descriptor: int | None = None
    with suppress(FileExistsError):
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, _PRIVATE_FILE)
    created = descriptor is not None
    if descriptor is None:
        _validate_file(path.lstat())
        descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        _validate_file(os.fstat(stream.fileno()))
    return created


def _validate_identity(path: Path) -> None:
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)) as inspection:
        application = cast("tuple[int]", inspection.execute("PRAGMA application_id").fetchone())[0]
        version = cast("tuple[int]", inspection.execute("PRAGMA user_version").fetchone())[0]
    if application != _APPLICATION_ID or version != _SCHEMA_VERSION:
        message = "dft_journal_identity_mismatch"
        raise ValueError(message)


def open_private_journal(path: Path, schema: str) -> sqlite3.Connection:
    """Open only newly created private state or this consumer's marked database.

    The immediate parent must already be private and owned by the current
    principal. Never create directories, chmod/chown, migrate unmarked state,
    or add tables to an existing unclaimed database. Admission still owns the
    exact allocation and approved principal; this is no runtime allocation.

    Returns:
        A connection whose caller owns closing and whose state is consumer-owned.
    """
    _validate_parent(path)
    created = _prepare_file(path)
    if not created:
        _validate_identity(path)
    with ExitStack() as failure_cleanup:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=rw", uri=True)
        failure_cleanup.callback(connection.close)
        connection.execute("PRAGMA synchronous=FULL")
        if created:
            connection.executescript(
                f"BEGIN IMMEDIATE;{schema}\nPRAGMA application_id={_APPLICATION_ID};"
                f"PRAGMA user_version={_SCHEMA_VERSION};COMMIT;",
            )
        failure_cleanup.pop_all()
        return connection
