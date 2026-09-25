# Copyright (c) 2026 PitchAI. All rights reserved.
"""Cross-process and crash-visible sandbox UID lease probes."""

from __future__ import annotations

import asyncio
import multiprocessing
from typing import TYPE_CHECKING

import pytest

from e2e_registry.testing import require_test_condition
from e2e_runner.isolation import terminate_uid_processes
from e2e_runner.uid_lease_config import LEASE_DIRECTORY_ENVIRONMENT, SandboxLeaseError
from e2e_runner.uid_leases import release_uid_lease, try_acquire_uid_lease
from tests.e2e_runner_lease_process_support import (
    attempt_uid_lease,
    hold_sandbox_uid,
    leave_dirty_uid_lease,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from multiprocessing.process import BaseProcess
    from multiprocessing.synchronize import Event
    from pathlib import Path

_LEASE_UID = 64_999
_LIVE_OWNER_UID = 64_998
_PROCESS_JOIN_SECONDS = 10


def _start_process(
    target: Callable[[int, str, str], None],
    arguments: tuple[int, str, str],
) -> BaseProcess:
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=target, args=arguments)
    process.start()
    return process


def _join_successfully(process: BaseProcess) -> None:
    process.join(timeout=_PROCESS_JOIN_SECONDS)
    require_test_condition(condition=not process.is_alive(), message="lease probe process must exit")
    require_test_condition(condition=process.exitcode == 0, message="lease probe process must succeed")


def _verify_blocked_contender(process: BaseProcess, *, result_path: Path) -> None:
    _join_successfully(process)
    require_test_condition(
        condition=result_path.read_text(encoding="utf-8") == "blocked",
        message="an independent runner must observe the held UID lease",
    )


async def _verify_live_owner(process: BaseProcess, ready: Event) -> None:
    ready_is_set = await asyncio.to_thread(ready.wait, _PROCESS_JOIN_SECONDS)
    require_test_condition(condition=ready_is_set, message="UID owner process must become ready")
    require_test_condition(
        condition=try_acquire_uid_lease(_LIVE_OWNER_UID) is None,
        message="a live owner must quarantine an otherwise clean UID",
    )
    await terminate_uid_processes(_LIVE_OWNER_UID)
    await asyncio.to_thread(process.join, _PROCESS_JOIN_SECONDS)
    require_test_condition(
        condition=not process.is_alive(),
        message="pidfd cleanup must kill the UID owner",
    )


def test_uid_lease_requires_explicit_shared_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Library callers must not silently lease from a container-local fallback."""
    monkeypatch.delenv(LEASE_DIRECTORY_ENVIRONMENT, raising=False)

    with pytest.raises(SandboxLeaseError, match="shared mounted lease directory"):
        try_acquire_uid_lease(_LEASE_UID)


def test_uid_lease_blocks_an_independent_runner_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Two supervisor processes must never hold the same UID concurrently."""
    lease_directory = tmp_path / "leases"
    monkeypatch.setenv(LEASE_DIRECTORY_ENVIRONMENT, str(lease_directory))
    parent_lease = try_acquire_uid_lease(_LEASE_UID)
    require_test_condition(condition=parent_lease is not None, message="parent must acquire the probe UID")
    result_path = tmp_path / "contender.txt"
    process = _start_process(
        attempt_uid_lease,
        (_LEASE_UID, str(lease_directory), str(result_path)),
    )
    try:
        _verify_blocked_contender(process, result_path=result_path)
    finally:
        if parent_lease is not None:
            release_uid_lease(parent_lease)


def test_crash_visible_lease_requires_explicit_recovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An unlocked active marker must quarantine a UID until startup recovery."""
    lease_directory = tmp_path / "leases"
    monkeypatch.setenv(LEASE_DIRECTORY_ENVIRONMENT, str(lease_directory))
    result_path = tmp_path / "crashed.txt"
    process = _start_process(
        leave_dirty_uid_lease,
        (_LEASE_UID, str(lease_directory), str(result_path)),
    )
    _join_successfully(process)
    require_test_condition(
        condition=result_path.read_text(encoding="utf-8") == "active",
        message="the child must persist active lifecycle state before exiting",
    )
    require_test_condition(
        condition=try_acquire_uid_lease(_LEASE_UID) is None,
        message="normal acquisition must quarantine crash-dirty state",
    )
    recovery_lease = try_acquire_uid_lease(_LEASE_UID, allow_stale=True)
    require_test_condition(condition=recovery_lease is not None, message="startup must recover stale state")
    if recovery_lease is not None:
        release_uid_lease(recovery_lease)


@pytest.mark.asyncio
async def test_uid_with_preexisting_live_owner_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A live process owner blocks reuse even when persisted state is clean."""
    monkeypatch.setenv(LEASE_DIRECTORY_ENVIRONMENT, str(tmp_path / "leases"))
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    process = context.Process(target=hold_sandbox_uid, args=(_LIVE_OWNER_UID, ready))
    process.start()
    try:
        await _verify_live_owner(process, ready)
    finally:
        if process.is_alive():
            await terminate_uid_processes(_LIVE_OWNER_UID)
            await asyncio.to_thread(process.join, _PROCESS_JOIN_SECONDS)
