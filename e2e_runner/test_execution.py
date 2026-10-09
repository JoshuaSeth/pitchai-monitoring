# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated job classification, submitted output and private HOME ownership."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from anyio import Path as AsyncPath

from domain_checks.dft_test_support import require
from domain_checks.metrics_synthetic import SyntheticTransactionResult

from .code_process import CodeProcess, extract_result_json, sandbox_environment
from .config import RunnerConfig
from .job import read_stepflow_result, run_one_job
from .job_result import JobRequest, JobResult

if TYPE_CHECKING:
    from httpx import AsyncClient
    from playwright.async_api import Browser

    from domain_checks.event_bus_delivery import JsonObject


class JobTests(unittest.IsolatedAsyncioTestCase):
    """Mock every external edge; only private temporary files are touched."""

    @staticmethod
    async def test_job_cancellation_and_reporting_failure_propagate() -> None:
        """Cancellation emits no completion; an unsuccessful completion is not hidden."""
        with TemporaryDirectory(prefix="runner-job-test-") as directory:
            cfg = RunnerConfig("http://registry.invalid", "synthetic", directory, directory, 1, 1,
                               trace_on_failure=False, code_exec_mode="local")
            client = cast("AsyncClient", MagicMock())
            browser = cast("Browser", MagicMock())
            job: JsonObject = {"run_id": "one", "test_id": "test", "definition": {}}
            probe = AsyncMock(side_effect=asyncio.CancelledError)
            with patch("e2e_runner.job.run_synthetic_transactions", new=probe), \
                    patch("e2e_runner.job.complete_job", new=AsyncMock()) as complete:
                observed = await asyncio.gather(run_one_job(browser, cfg, client, job), return_exceptions=True)
            require(condition=isinstance(observed[0], asyncio.CancelledError), message="cancellation was reported")
            complete.assert_not_awaited()
            with patch("e2e_runner.job.complete_job", new=AsyncMock(side_effect=ValueError("delivery"))):
                observed = await asyncio.gather(run_one_job(None, cfg, client, job), return_exceptions=True)
            require(condition=isinstance(observed[0], ValueError) and str(observed[0]) == "delivery",
                    message="completion failure was hidden")

    @staticmethod
    async def test_invalid_source_never_admits_process() -> None:
        """Parent traversal is refused and still reports the existing failed result."""
        with TemporaryDirectory(prefix="runner-source-test-") as directory:
            cfg = RunnerConfig("http://registry.invalid", "synthetic", directory, directory, 1, 1,
                               trace_on_failure=False, code_exec_mode="local")
            client = cast("AsyncClient", MagicMock())
            with patch("e2e_runner.job.CodeProcess.run", new=AsyncMock()) as execute, \
                    patch("e2e_runner.job.complete_job", new=AsyncMock()) as complete:
                await run_one_job(None, cfg, client, {"test_kind": "playwright_python", "source_relpath": "../outside"})
            execute.assert_not_awaited()
            payload = cast("JsonObject", complete.call_args.kwargs["payload"])
            require(condition=payload["status"] == "fail" and payload["error_kind"] == "invalid_source_path",
                    message="source containment classification changed")

    @staticmethod
    async def test_child_home_is_private_allowlisted_and_removed() -> None:
        """The mocked process gets its own HOME and no inherited secret."""
        request = JobRequest("run", "test", "tenant", "https://a.invalid", 5.0, "playwright_python", None, "test.py")
        execute = AsyncMock()

        async def communicate() -> tuple[bytes, bytes]:
            environment = cast("dict[str, str]", execute.call_args.kwargs["env"])
            permissions = await AsyncPath(environment["HOME"]).stat()
            require(condition=permissions.st_mode & 0o077 == 0,
                    message="child HOME permits another principal")
            return b'E2E_RESULT_JSON={"status":"pass"}', b"warning"

        execute.return_value = MagicMock(communicate=communicate)
        with TemporaryDirectory(prefix="runner-process-test-") as directory, \
                patch("e2e_runner.code_process.asyncio.create_subprocess_exec", new=execute), \
                patch.dict("os.environ", {"RUNNER_PRIVATE_TEST_SECRET": "never-forward"}):
            parsed, output = await CodeProcess(request, Path(directory) / "test.py", Path(directory), trace=True).run()
            environment = cast("dict[str, str]", execute.call_args.kwargs["env"])
            home = Path(environment["HOME"])
            require(condition=not await AsyncPath(home).exists(), message="owned HOME was not removed")
            require(condition="RUNNER_PRIVATE_TEST_SECRET" not in environment, message="secret crossed child boundary")
            require(condition=parsed == {"status": "pass"} and output.endswith("warning"),
                    message="result parsing or output changed")
            last_argument = cast("str", execute.call_args.args[-1])
            require(condition=last_argument == "--trace-on-failure", message="command flags changed")

    @staticmethod
    async def test_process_failure_kills_without_fabricating_result() -> None:
        """Ordinary communication failures retain their exception and attempt kill."""
        request = JobRequest("r", "t", "tenant", "u", 5.0, "puppeteer_js", None, "test.js")
        kill = MagicMock()
        process = MagicMock(communicate=AsyncMock(side_effect=ValueError("communication")), kill=kill)
        with TemporaryDirectory(prefix="runner-process-test-") as directory, \
                patch("e2e_runner.code_process.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)):
            candidate = CodeProcess(request, Path(directory) / "test.js", Path(directory), trace=False)
            result = await asyncio.gather(candidate.run(),
                                          return_exceptions=True)
        kill.assert_called_once_with()
        require(condition=isinstance(result[0], ValueError) and str(result[0]) == "communication",
                message="child failure was replaced")

    @staticmethod
    async def test_stepflow_artifact_order_and_success_omission() -> None:
        """Failure-only artifacts preserve their original fixed-key then screenshot order."""
        details: JsonObject = {"screenshot_two": "two.png", "run_log": " run.log ", "title": "title",
                               "failure_screenshot": "failure.png", "trace_zip": "trace.zip", "final_url": "u"}
        observation = SyntheticTransactionResult("d", "n", ok=False, elapsed_ms=1.0, error="failed", details=details,
                                                  browser_infra_error=False)
        result = JobResult()
        read_stepflow_result(result, observation)
        require(condition=list(result.artifacts) == ["failure_screenshot", "trace_zip", "run_log", "screenshot_two"],
                message="artifact order changed")
        success = JobResult()
        read_stepflow_result(success, SyntheticTransactionResult("d", "n", ok=True, elapsed_ms=1.0, error=None,
                                                                details=details, browser_infra_error=False))
        require(condition=success.status == "pass" and success.title is None and not success.artifacts,
                message="success acquired failure-only data")

    @staticmethod
    async def test_last_result_line_and_environment_contract() -> None:
        """A malformed final result does not reuse success; child values override only allowed keys."""
        value = extract_result_json('E2E_RESULT_JSON={"status":"pass"}\nE2E_RESULT_JSON={bad}')
        require(condition=value is None, message="invalid last result reused an earlier success")
        request = JobRequest("r", "t", "tenant", "u", 1, "stepflow", {}, None)
        original = {"PUPPETEER_TEST": "kept", "LC_TEST": "locale", "HOME": "not-inherited"}
        with patch.dict("os.environ", original, clear=True):
            environment = sandbox_environment(request, Path("artifacts"), "private-home")
        require(condition=environment == {"PUPPETEER_TEST": "kept", "LC_TEST": "locale", "HOME": "private-home",
                                          "BASE_URL": "u", "ARTIFACTS_DIR": "artifacts"}, message="allowlist changed")
