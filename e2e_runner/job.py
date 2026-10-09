# Copyright (c) 2026 PitchAI. All rights reserved.
"""Native registry job execution with explicit StepFlow and submitted-code phases."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from domain_checks.browser_failure import BrowserFailure
from domain_checks.metrics_synthetic import run_synthetic_transactions

from .code_process import CodeProcess
from .job_result import JobRequest, JobResult
from .transport import complete_job

if TYPE_CHECKING:
    from httpx import AsyncClient
    from playwright.async_api import Browser

    from domain_checks.event_bus_delivery import JsonObject
    from domain_checks.metrics_synthetic import SyntheticTransactionResult

    from .config import RunnerConfig


def read_stepflow_result(result: JobResult, observation: SyntheticTransactionResult) -> None:
    """Preserve successful measurements and failed-only title/artifact publication."""
    result.elapsed_ms = observation.elapsed_ms
    result.final_url = (observation.details or {}).get("final_url")
    if observation.ok:
        result.status = "pass"
        return
    result.title = (observation.details or {}).get("title")
    kind = "browser_infra_error" if observation.browser_infra_error else "assertion_failed"
    status = "infra_degraded" if observation.browser_infra_error else "fail"
    result.fail(status, kind, observation.error)
    for key in ("failure_screenshot", "trace_zip", "run_log"):
        value = observation.details.get(key)
        if isinstance(value, str) and value.strip():
            result.artifacts[key] = value.strip()
    for key, value in observation.details.items():
        if key.startswith("screenshot_") and isinstance(value, str) and value.strip():
            result.artifacts[key] = value.strip()


@dataclass
class JobExecution:
    """Own the normalized request, existing artifact directory and partial result."""

    cfg: RunnerConfig
    request: JobRequest
    directory: Path
    result: JobResult

    async def stepflow(self, browser: Browser | None) -> None:
        """Execute the existing single transaction after browser/definition validation."""
        if browser is None:
            self.result.fail("infra_degraded", "browser_unavailable", "runner has no browser instance")
            return
        definition = self.request.definition
        if not isinstance(definition, dict):
            self.result.fail("fail", "invalid_definition", "definition must be an object")
            return
        results = await run_synthetic_transactions(
            domain=self.request.test_id or "test", base_url=self.request.base_url,
            browser=browser, transactions=[definition], timeout_seconds=self.request.timeout,
            artifacts_dir=str(self.directory), trace_on_failure=bool(self.cfg.trace_on_failure),
        )
        observation = results[0] if results else None
        if observation is None:
            self.result.fail("fail", "runner_error", "no_result")
            return
        read_stepflow_result(self.result, observation)

    async def code(self) -> None:
        """Validate source containment before running code and retaining its submitted result."""
        if self.request.kind not in {"playwright_python", "puppeteer_js"}:
            self.result.fail("fail", "invalid_kind", f"unsupported_test_kind: {self.request.kind}")
            return
        if not self.request.source:
            self.result.fail("fail", "missing_source", "source_relpath is required for code tests")
            return
        test_file = self.code_file(self.request.source)
        if test_file is None:
            return
        process = CodeProcess(self.request, test_file, self.directory, bool(self.cfg.trace_on_failure))
        parsed, combined = await process.run()
        self.result.write_output(self.directory, combined)
        if parsed:
            self.result.read_parsed(parsed)
        else:
            self.result.fail("fail", "missing_result_json", "runner output did not include E2E_RESULT_JSON")

    def code_file(self, source: str) -> Path | None:
        """Resolve and validate the native source file before admitting a child process.

        Returns:
            The existing contained file, otherwise records the original refusal.
        """
        test_file = (Path(self.cfg.tests_dir).resolve() / source).resolve()
        base_tests = Path(self.cfg.tests_dir).resolve()
        if base_tests not in test_file.parents:
            self.result.fail("fail", "invalid_source_path", "source_relpath resolves outside tests_dir")
            return None
        if not test_file.exists() or not test_file.is_file():
            self.result.fail("fail", "source_not_found", f"missing_file: {test_file}")
            return None
        return test_file


async def run_one_job(browser: Browser | None, cfg: RunnerConfig, client: AsyncClient, job: JsonObject) -> None:
    """Report ordinary job failures without converting cancellation or completion errors."""
    request = JobRequest.parse(job)
    started = time.time()
    result = JobResult()
    directory = Path(cfg.artifacts_dir) / request.tenant_id / request.test_id / request.run_id
    directory.mkdir(parents=True, exist_ok=True)
    execution = JobExecution(cfg, request, directory, result)
    with BrowserFailure() as failure:
        if request.kind == "stepflow":
            await execution.stepflow(browser)
        else:
            await execution.code()
    if failure.error is not None:
        result.fail("infra_degraded", type(failure.error).__name__, str(failure.error))
    finished = time.time()
    payload = result.payload(started, finished)
    await complete_job(client, cfg, run_id=request.run_id, payload=payload)
