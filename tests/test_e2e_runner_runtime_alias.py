# Copyright (c) 2026 PitchAI. All rights reserved.
"""Fail-closed contracts for short submitted-browser runtime aliases."""

from __future__ import annotations

import os
import socket
import stat
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from e2e_registry.testing import require_test_condition
from e2e_runner import runtime_alias
from e2e_runner.code_execution import build_sandbox_environment
from e2e_runner.isolation import (
    acquire_submission_identity,
    prepare_submission_filesystem,
    release_submission_identity,
    seal_submission_filesystem,
)
from e2e_runner.uid_lease_config import LEASE_DIRECTORY_ENVIRONMENT

if TYPE_CHECKING:
    from collections.abc import Iterator

_SANDBOX_GID = 65_534
_UNTRUSTED_UID = 60_000
_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600
_RUNTIME_ROOT_MODE = 0o711
_UNIX_SOCKET_PATH_LIMIT = 108


@pytest.fixture(name="runtime_root")
def provide_runtime_root(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Use one short, root-owned runtime location and remove it after each probe.

    Yields:
        The isolated runtime-alias root used by the probe.
    """
    root = Path("/run") / f"pitchai-e2e-alias-test-{uuid.uuid4().hex[:10]}"
    monkeypatch.setattr(runtime_alias, "RUNTIME_ALIAS_ROOT", root)
    try:
        yield root
    finally:
        if root.is_dir():
            for entry in root.iterdir():
                entry.unlink()
            root.rmdir()


def _prepare_private_target(root: Path, *, uid: int, long_path: bool) -> Path:
    parent = root
    if long_path:
        parent = parent / ("tenant-" + "a" * 64) / ("test-" + "b" * 64) / ("run-" + "c" * 64)
    target = parent / "sandbox-tmp"
    target.mkdir(parents=True)
    os.chown(target, uid, _SANDBOX_GID)
    target.chmod(_PRIVATE_DIRECTORY_MODE)
    return target


def _create_runtime_root(root: Path) -> None:
    root.mkdir(mode=_RUNTIME_ROOT_MODE)
    os.chown(root, 0, 0)
    root.chmod(_RUNTIME_ROOT_MODE)


def test_long_private_target_uses_short_protected_alias(
    runtime_root: Path,
    tmp_path: Path,
) -> None:
    """A long artifact path must retain ownership while Chromium sees a short TMPDIR."""
    target = _prepare_private_target(tmp_path, uid=_UNTRUSTED_UID, long_path=True)
    alias = runtime_alias.prepare_runtime_alias(
        uid=_UNTRUSTED_UID,
        target_directory=target,
    )
    root_stat = runtime_root.lstat()
    target_stat = target.lstat()
    alias_stat = alias.lstat()

    require_test_condition(
        condition=len(str(target)) > _UNIX_SOCKET_PATH_LIMIT,
        message="the private target must reproduce the Chromium Unix-socket limit",
    )
    require_test_condition(
        condition=len(str(alias)) < _UNIX_SOCKET_PATH_LIMIT,
        message="runtime alias must keep Chromium socket paths below the Unix limit",
    )
    require_test_condition(
        condition=root_stat.st_uid == 0
        and stat.S_IMODE(root_stat.st_mode) == _RUNTIME_ROOT_MODE,
        message="runtime alias root must be root-owned mode 0711",
    )
    require_test_condition(
        condition=target_stat.st_uid == _UNTRUSTED_UID
        and stat.S_IMODE(target_stat.st_mode) == _PRIVATE_DIRECTORY_MODE,
        message="runtime alias target must remain private to the leased UID",
    )
    require_test_condition(
        condition=stat.S_ISLNK(alias_stat.st_mode)
        and alias_stat.st_uid == 0
        and alias.readlink() == target.absolute(),
        message="runtime alias must be an exact root-owned link to the private target",
    )
    require_test_condition(
        condition=runtime_alias.recorded_runtime_alias_uids() == {_UNTRUSTED_UID},
        message="startup recovery must discover every validated alias UID",
    )
    long_socket_path = target / "chromium.sock"
    with (
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as long_socket,
        pytest.raises(OSError, match="AF_UNIX path too long"),
    ):
        long_socket.bind(str(long_socket_path))
    short_socket_path = alias / "chromium.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as short_socket:
        short_socket.bind(str(short_socket_path))
        require_test_condition(
            condition=stat.S_ISSOCK(short_socket_path.stat().st_mode),
            message="the short alias must create the Unix socket in the private target",
        )
    short_socket_path.unlink()
    runtime_alias.remove_runtime_alias(
        uid=_UNTRUSTED_UID,
        expected_target=target,
    )


def test_preexisting_or_tampered_alias_fails_closed(runtime_root: Path, tmp_path: Path) -> None:
    """Alias reuse and an exact-target substitution must stop UID preparation."""
    target = _prepare_private_target(tmp_path / "original", uid=_UNTRUSTED_UID, long_path=False)
    _create_runtime_root(runtime_root)
    alias = runtime_alias.runtime_alias_path(_UNTRUSTED_UID)
    _ = alias.write_text("occupied", encoding="utf-8")
    with pytest.raises(runtime_alias.SandboxRuntimeAliasError, match=r"unexpected.*entry"):
        _ = runtime_alias.prepare_runtime_alias(
            uid=_UNTRUSTED_UID,
            target_directory=target,
        )
    alias.unlink()

    alias = runtime_alias.prepare_runtime_alias(
        uid=_UNTRUSTED_UID,
        target_directory=target,
    )
    alias.unlink()
    replacement = _prepare_private_target(
        tmp_path / "replacement",
        uid=_UNTRUSTED_UID,
        long_path=False,
    )
    _ = alias.symlink_to(replacement, target_is_directory=True)
    with pytest.raises(runtime_alias.SandboxRuntimeAliasError, match="target changed"):
        runtime_alias.remove_runtime_alias(
            uid=_UNTRUSTED_UID,
            expected_target=target,
        )
    alias.unlink()


def test_unexpected_runtime_root_entry_is_never_ignored(runtime_root: Path) -> None:
    """Unexpected root entries must fail loudly instead of consuming UID aliases."""
    _create_runtime_root(runtime_root)
    unexpected = runtime_root / "unmanaged-entry"
    _ = unexpected.symlink_to(runtime_root.parent, target_is_directory=True)
    with pytest.raises(runtime_alias.SandboxRuntimeAliasError, match=r"unexpected.*entry"):
        runtime_alias.remove_runtime_alias(uid=_UNTRUSTED_UID)
    unexpected.unlink()


def test_normal_identity_cleanup_removes_exact_runtime_alias(
    runtime_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A sealed successful identity must leave no alias before UID reuse."""
    monkeypatch.setenv(LEASE_DIRECTORY_ENVIRONMENT, str(tmp_path / "leases"))
    run_directory = tmp_path / "artifacts" / "tenant" / "test" / "run"
    run_directory.mkdir(parents=True, mode=_PRIVATE_DIRECTORY_MODE)
    run_directory.chmod(_PRIVATE_DIRECTORY_MODE)
    staged_source = run_directory / "verified_source.py"
    _ = staged_source.write_text("# verified\n", encoding="utf-8")
    staged_source.chmod(_PRIVATE_FILE_MODE)
    identity = acquire_submission_identity(
        artifacts_directory=run_directory,
        trusted_credentials={},
    )
    prepare_submission_filesystem(
        artifacts_directory=run_directory,
        staged_source=staged_source,
        identity=identity,
    )
    environment = build_sandbox_environment(
        base_url="https://target.invalid",
        artifacts_dir=run_directory,
        identity=identity,
    )
    require_test_condition(
        condition=environment["TMPDIR"] == str(identity.temporary_alias)
        and identity.temporary_alias.is_symlink(),
        message="submitted processes must receive the protected short runtime alias",
    )
    seal_submission_filesystem(run_directory)
    release_submission_identity(identity)
    require_test_condition(
        condition=not identity.temporary_alias.is_symlink() and not any(runtime_root.iterdir()),
        message="normal cleanup must remove the exact alias before releasing its UID",
    )
