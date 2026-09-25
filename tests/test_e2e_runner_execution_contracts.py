# Copyright (c) 2026 PitchAI. All rights reserved.
"""Focused contracts for runner timing and submitted-process failures."""

from __future__ import annotations

import asyncio
import stat
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, cast, final

import pytest

from e2e_registry.testing import require_test_condition
from e2e_runner.code_execution import extract_result_json, interpret_process_capture
from e2e_runner.models import JobResult, RunnerConfig, RunnerJob
from e2e_runner.process_gateway import collect_process_output
from e2e_runner.service import execute_timed_job

_PUBLIC_SOURCE_MODE = 0o644

if TYPE_CHECKING:
    from asyncio.subprocess import Process

    from playwright.async_api import Browser


@final
class DeadlineProcess:
    """Process double whose first communication never meets its deadline."""

    def __init__(self) -> None:
        """Initialize a live synthetic process."""
        self._returncode: int | None = None
        self.killed = False

    @property
    def returncode(self) -> int | None:
        """Return the synthetic process code."""
        return self._returncode

    async def communicate(self) -> tuple[bytes | None, bytes | None]:
        """Block until killed, then expose bounded partial output.

        Returns:
            The captured stdout and stderr byte streams.
        """
        if not self.killed:
            _ = await asyncio.Event().wait()
        return b"partial stdout", b"deadline reached"

    async def terminate_stably(self) -> None:
        """Model the stable UID cleanup invoked at the deadline."""
        self.killed = True
        self._returncode = -9


def _runner_job(*, test_id: str) -> RunnerJob:
    return RunnerJob(
        run_id=f"run-{test_id}",
        test_id=test_id,
        tenant_id="tenant-id",
        test_name=f"test-{test_id}",
        base_url="https://target.invalid",
        timeout_seconds=5.0,
        test_kind="playwright_python",
        definition={},
        source_relpath="tenant/test.py",
        source_filename="test.py",
        source_sha256="0" * 64,
    )


@pytest.mark.asyncio
async def test_each_concurrent_job_keeps_its_own_execution_interval(tmp_path: Path) -> None:
    """A fast job must not inherit a slower batch sibling's finish timestamp."""
    config = RunnerConfig(
        registry_base_url="https://registry.invalid",
        runner_token=uuid.uuid4().hex,
        artifacts_dir=tmp_path / "artifacts",
        tests_dir=tmp_path / "tests",
        poll_seconds=1.0,
        concurrency=2,
        trace_on_failure=False,
    )

    async def delayed_executor(
        _browser: Browser | None,
        _config: RunnerConfig,
        job: RunnerJob,
    ) -> JobResult:
        await asyncio.sleep(0.04 if job.test_id == "slow" else 0.001)
        return JobResult(status="pass")

    slow_envelope, fast_envelope = await asyncio.gather(
        execute_timed_job(
            browser=None,
            config=config,
            job=_runner_job(test_id="slow"),
            executor=delayed_executor,
        ),
        execute_timed_job(
            browser=None,
            config=config,
            job=_runner_job(test_id="fast"),
            executor=delayed_executor,
        ),
    )

    require_test_condition(
        condition=fast_envelope.finished_at_ts < slow_envelope.finished_at_ts,
        message="the fast job must retain its earlier completion timestamp",
    )
    require_test_condition(
        condition=fast_envelope.started_at_ts <= fast_envelope.finished_at_ts,
        message="each job interval must be monotonic",
    )


@pytest.mark.asyncio
async def test_timeout_is_a_declared_code_execution_failure() -> None:
    """A submitted-process deadline must not become an unexpected runner crash."""
    process = DeadlineProcess()

    process_boundary = cast("Process", cast("object", process))
    capture = await collect_process_output(
        process_boundary,
        deadline_seconds=0.001,
        timeout_cleanup=process.terminate_stably,
    )
    execution = interpret_process_capture(capture)

    require_test_condition(
        condition=process.killed,
        message="the timed-out process must be terminated",
    )
    require_test_condition(
        condition=execution.parsed_result.error_kind == "code_execution_timeout",
        message="a submitted-code deadline must retain its stable failure kind",
    )
    require_test_condition(
        condition="partial stdout" in execution.combined_output,
        message="timeout diagnostics must preserve the process output collected after termination",
    )


def test_malformed_result_json_is_distinct_from_missing_output() -> None:
    """Malformed untrusted JSON must retain its explicit protocol contract."""
    malformed = extract_result_json("E2E_RESULT_JSON={not-json}")
    missing = extract_result_json("sandbox exited without a result marker")

    require_test_condition(
        condition=malformed.error_kind == "invalid_result_json",
        message="a malformed marker must report invalid_result_json",
    )
    require_test_condition(
        condition=missing.error_kind == "missing_result_json",
        message="an absent marker must remain distinct from malformed JSON",
    )


def test_container_makes_puppeteer_runtime_readable_after_copy() -> None:
    """The image build must normalize the JS runtime after copying source metadata."""
    repository_root = Path(__file__).resolve().parent.parent
    dockerfile_text = (repository_root / "Dockerfile").read_text(encoding="utf-8")
    copy_position = dockerfile_text.index("COPY e2e_sandbox ./e2e_sandbox")
    mode_position = dockerfile_text.index(
        "RUN chmod 0644 /app/e2e_sandbox/puppeteer_js_runner.js",
    )
    source_mode = stat.S_IMODE(
        (repository_root / "e2e_sandbox" / "puppeteer_js_runner.js").stat().st_mode,
    )

    require_test_condition(
        condition=copy_position < mode_position,
        message="the image must normalize the Puppeteer runtime after COPY preserves host mode",
    )
    require_test_condition(
        condition=source_mode == _PUBLIC_SOURCE_MODE,
        message="the local Puppeteer runtime must be readable for dropped-UID bind validation",
    )
