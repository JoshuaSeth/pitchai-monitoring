# Copyright (c) 2026 PitchAI. All rights reserved.
"""Short, protected runtime aliases for browser subprocess temporary files."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

RUNTIME_ALIAS_ROOT = Path("/run/pitchai-e2e-sandbox")
_RUNTIME_ROOT_MODE = 0o711
_PRIVATE_DIRECTORY_MODE = 0o700
_ALIAS_PREFIX = "tmp-"
_ALIAS_NAME_PATTERN = re.compile(r"tmp-([1-9][0-9]*)")
_TRUSTED_UID_RANGE = range(55_000, 56_000)
_UNTRUSTED_UID_RANGE = range(60_000, 65_000)


class SandboxRuntimeAliasError(RuntimeError):
    """Raised when the protected browser-runtime alias contract is violated."""


def runtime_alias_path(uid: int) -> Path:
    """Return the supervisor-owned short alias reserved for one leased UID."""
    return RUNTIME_ALIAS_ROOT / f"{_ALIAS_PREFIX}{uid}"


def _require_root_supervisor() -> None:
    if os.geteuid() != 0:
        message = "sandbox runtime alias management requires a root runner supervisor"
        raise SandboxRuntimeAliasError(message)


def _validate_runtime_root() -> None:
    root_stat = RUNTIME_ALIAS_ROOT.lstat()
    valid = (
        stat.S_ISDIR(root_stat.st_mode)
        and root_stat.st_uid == 0
        and stat.S_IMODE(root_stat.st_mode) == _RUNTIME_ROOT_MODE
    )
    if not valid:
        message = (
            "sandbox runtime alias root must be a root-owned "
            f"mode-{_RUNTIME_ROOT_MODE:04o} directory: {RUNTIME_ALIAS_ROOT}"
        )
        raise SandboxRuntimeAliasError(message)


def _validate_runtime_entries() -> None:
    for entry in RUNTIME_ALIAS_ROOT.iterdir():
        entry_stat = entry.lstat()
        match = _ALIAS_NAME_PATTERN.fullmatch(entry.name)
        target = entry.readlink() if stat.S_ISLNK(entry_stat.st_mode) else None
        uid = int(match.group(1)) if match is not None else None
        valid = (
            uid is not None
            and (uid in _TRUSTED_UID_RANGE or uid in _UNTRUSTED_UID_RANGE)
            and stat.S_ISLNK(entry_stat.st_mode)
            and entry_stat.st_uid == 0
            and target is not None
            and target.is_absolute()
            and target.name == "sandbox-tmp"
        )
        if not valid:
            message = f"unexpected sandbox runtime alias root entry: {entry}"
            raise SandboxRuntimeAliasError(message)


def _prepare_runtime_root() -> None:
    _require_root_supervisor()
    try:
        RUNTIME_ALIAS_ROOT.mkdir(mode=_RUNTIME_ROOT_MODE)
    except FileExistsError:
        pass
    else:
        os.chown(RUNTIME_ALIAS_ROOT, 0, 0)
        RUNTIME_ALIAS_ROOT.chmod(_RUNTIME_ROOT_MODE)
    _validate_runtime_root()
    _validate_runtime_entries()


def _validate_target(target_directory: Path, *, uid: int) -> Path:
    absolute_target = target_directory.absolute()
    target_stat = absolute_target.lstat()
    valid = (
        (uid in _TRUSTED_UID_RANGE or uid in _UNTRUSTED_UID_RANGE)
        and absolute_target.name == "sandbox-tmp"
        and stat.S_ISDIR(target_stat.st_mode)
        and target_stat.st_uid == uid
        and stat.S_IMODE(target_stat.st_mode) == _PRIVATE_DIRECTORY_MODE
    )
    if not valid:
        message = (
            "sandbox runtime alias target must be the leased UID's "
            f"mode-{_PRIVATE_DIRECTORY_MODE:04o} directory: {absolute_target}"
        )
        raise SandboxRuntimeAliasError(message)
    return absolute_target


def prepare_runtime_alias(*, uid: int, target_directory: Path) -> Path:
    """Create a protected short alias to one private per-run temporary directory.

    Returns:
        The root-owned alias path suitable for ``TMPDIR``.

    Raises:
        SandboxRuntimeAliasError: If the alias root or target is unsafe or reused.
    """
    _prepare_runtime_root()
    target = _validate_target(target_directory, uid=uid)
    alias = runtime_alias_path(uid)
    try:
        alias.symlink_to(target, target_is_directory=True)
    except FileExistsError as exc:
        message = f"sandbox runtime alias already exists for leased UID {uid}: {alias}"
        raise SandboxRuntimeAliasError(message) from exc
    alias_stat = alias.lstat()
    if not stat.S_ISLNK(alias_stat.st_mode) or alias_stat.st_uid != 0:
        message = f"sandbox runtime alias must be a root-owned symbolic link: {alias}"
        raise SandboxRuntimeAliasError(message)
    return alias


def _read_alias_target(alias: Path) -> Path:
    alias_stat = alias.lstat()
    if not stat.S_ISLNK(alias_stat.st_mode) or alias_stat.st_uid != 0:
        message = f"sandbox runtime alias must be a root-owned symbolic link: {alias}"
        raise SandboxRuntimeAliasError(message)
    target = alias.readlink()
    if not target.is_absolute():
        message = f"sandbox runtime alias target must be absolute: {alias}"
        raise SandboxRuntimeAliasError(message)
    return target


def recorded_runtime_alias_uids() -> set[int]:
    """Return every protected alias UID and reject unexpected root entries.

    Returns:
        UIDs represented by validated runtime aliases.
    """
    _require_root_supervisor()
    try:
        _ = RUNTIME_ALIAS_ROOT.lstat()
    except FileNotFoundError:
        return set()
    _validate_runtime_root()
    _validate_runtime_entries()
    return {
        int(alias.name.removeprefix(_ALIAS_PREFIX))
        for alias in RUNTIME_ALIAS_ROOT.iterdir()
    }


def remove_runtime_alias(
    *,
    uid: int,
    expected_target: Path | None = None,
    artifacts_root: Path | None = None,
) -> None:
    """Remove one validated alias after process termination and tree sealing.

    Raises:
        SandboxRuntimeAliasError: If an existing alias is not the protected link expected.
    """
    _require_root_supervisor()
    alias = runtime_alias_path(uid)
    try:
        _validate_runtime_root()
    except FileNotFoundError:
        return
    _validate_runtime_entries()
    try:
        target = _read_alias_target(alias)
    except FileNotFoundError:
        return
    if expected_target is not None and target != expected_target.absolute():
        message = f"sandbox runtime alias target changed for leased UID {uid}: {alias}"
        raise SandboxRuntimeAliasError(message)
    if artifacts_root is not None and not target.is_relative_to(artifacts_root.absolute()):
        message = f"recovered sandbox runtime alias points outside artifact storage: {alias}"
        raise SandboxRuntimeAliasError(message)
    alias.unlink()
