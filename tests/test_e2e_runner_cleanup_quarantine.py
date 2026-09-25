# Copyright (c) 2026 PitchAI. All rights reserved.
"""Quarantine contracts for incomplete submitted-job cleanup."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

import pytest

from e2e_registry.testing import require_test_condition
from e2e_runner import code_execution
from e2e_runner.execution_models import CodeExecutionRequest
from e2e_runner.isolation import acquire_submission_identity, release_submission_identity
from e2e_runner.process_gateway import ProcessCapture

if TYPE_CHECKING:
    from asyncio.subprocess import Process
    from collections.abc import Awaitable, Callable, Sequence
    from pathlib import Path

    from e2e_runner.isolation import SandboxIdentity


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_cleanup", ["termination", "sealing"])
async def test_cleanup_failure_quarantines_uid_lease(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failed_cleanup: str,
) -> None:
    """A UID must not return to the pool unless process cleanup and sealing both succeed."""
    captured_identity: list[SandboxIdentity] = []
    cleanup_calls: list[str] = []

    def prepare_filesystem(
        *,
        artifacts_directory: Path,
        staged_source: Path,
        identity: SandboxIdentity,
    ) -> None:
        del artifacts_directory, staged_source, identity

    async def launch_process(
        _command: list[str],
        *,
        environment: dict[str, str],
        identity: SandboxIdentity,
    ) -> Process:
        del environment
        await asyncio.sleep(0)
        captured_identity.append(identity)
        return cast("Process", object())

    async def collect_output(
        _process: Process,
        *,
        deadline_seconds: float,
        timeout_cleanup: Callable[[], Awaitable[None]],
        sensitive_values: Sequence[str],
    ) -> ProcessCapture:
        del sensitive_values, timeout_cleanup
        await asyncio.sleep(0)
        return ProcessCapture(
            stdout=b'E2E_RESULT_JSON={"status":"pass"}\n',
            stderr=b"",
            timed_out=False,
            deadline_seconds=deadline_seconds,
        )

    async def terminate_processes(_identity: SandboxIdentity) -> None:
        cleanup_calls.append("termination")
        await asyncio.sleep(0)
        if failed_cleanup == "termination":
            message = "injected termination failure"
            raise OSError(message)

    def seal_filesystem(_directory: Path) -> None:
        cleanup_calls.append("sealing")
        if failed_cleanup == "sealing":
            message = "injected sealing failure"
            raise OSError(message)

    monkeypatch.setattr(code_execution, "prepare_submission_filesystem", prepare_filesystem)
    monkeypatch.setattr(code_execution, "launch_isolated_process", launch_process)
    monkeypatch.setattr(code_execution, "collect_process_output", collect_output)
    monkeypatch.setattr(code_execution, "terminate_identity_processes", terminate_processes)
    monkeypatch.setattr(code_execution, "seal_submission_filesystem", seal_filesystem)
    request = CodeExecutionRequest(
        kind="playwright_python",
        test_file=tmp_path / "verified_source.py",
        base_url="https://target.invalid",
        artifacts_dir=tmp_path / "run",
        timeout_seconds=5.0,
        trace_on_failure=False,
        trusted_credentials={},
    )

    with pytest.raises(OSError, match=f"injected {failed_cleanup} failure"):
        await code_execution.run_code_local(request=request)

    require_test_condition(
        condition=cleanup_calls == ["termination", "sealing"],
        message="both cleanup phases must be attempted before quarantine",
    )
    quarantined = captured_identity[0]
    replacement = acquire_submission_identity(
        artifacts_directory=tmp_path / "replacement",
        trusted_credentials={},
    )
    try:
        require_test_condition(
            condition=replacement.uid != quarantined.uid,
            message="a cleanup-failed UID must remain quarantined from reuse",
        )
    finally:
        release_submission_identity(replacement)
        release_submission_identity(quarantined)
