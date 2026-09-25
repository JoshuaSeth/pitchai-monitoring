# Copyright (c) 2026 PitchAI. All rights reserved.
"""Execution dispatch and result normalization for claimed jobs."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Literal

from e2e_runner.code_execution import run_code_local
from e2e_runner.credentials import trusted_code_test_environment
from e2e_runner.execution_models import CodeExecutionRequest
from e2e_runner.integrity import SourceIntegrityFailure, stage_verified_source
from e2e_runner.models import JobResult
from e2e_runner.stepflow import run_stepflow
from e2e_runner.storage import ArtifactStorageError, prepare_job_directory, replace_private_file

if TYPE_CHECKING:
    from pathlib import Path

    from playwright.async_api import Browser

    from e2e_registry.models import JsonObject, JsonValue
    from e2e_runner.code_execution import CodeExecutionOutput
    from e2e_runner.models import JobStatus, RunnerConfig, RunnerJob

type CodeTestKind = Literal["playwright_python", "puppeteer_js"]
_CODE_TEST_KINDS: frozenset[str] = frozenset({"playwright_python", "puppeteer_js"})
_VALID_STATUSES: frozenset[str] = frozenset({"pass", "fail", "infra_degraded"})


def _optional_text(value: JsonValue) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _optional_float(value: JsonValue) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _result_artifacts(value: JsonValue) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    artifacts: JsonObject = {}
    for key, raw_artifact in value.items():
        artifact = _optional_text(raw_artifact)
        if artifact is not None:
            artifacts[key] = artifact
    return artifacts


def _code_result(payload: JsonObject) -> JobResult:
    raw_status = payload.get("status")
    if not isinstance(raw_status, str) or raw_status not in _VALID_STATUSES:
        return JobResult.failure(
            error_kind="invalid_result_json",
            error_message="sandbox result status is invalid",
        )
    if raw_status == "pass":
        status: JobStatus = "pass"
    elif raw_status == "fail":
        status = "fail"
    else:
        status = "infra_degraded"
    return JobResult(
        status=status,
        elapsed_ms=_optional_float(payload.get("elapsed_ms")),
        error_kind=_optional_text(payload.get("error_kind")),
        error_message=_optional_text(payload.get("error_message")),
        final_url=_optional_text(payload.get("final_url")),
        title=_optional_text(payload.get("title")),
        artifacts=_result_artifacts(payload.get("artifacts")),
    )


async def _prepare_output_directory(*, config: RunnerConfig, job: RunnerJob) -> Path | JobResult:
    try:
        return await asyncio.to_thread(
            prepare_job_directory,
            artifacts_root=config.artifacts_dir,
            tenant_id=job.tenant_id,
            test_id=job.test_id,
            run_id=job.run_id,
        )
    except (ArtifactStorageError, OSError) as exc:
        return JobResult.failure(
            error_kind="artifact_storage_rejected",
            error_message=str(exc),
        )


def _finalize_code_result(execution: CodeExecutionOutput) -> JobResult:
    parsed_result = execution.parsed_result
    if parsed_result.error_kind is not None:
        return JobResult(
            status="fail",
            error_kind=parsed_result.error_kind,
            error_message=parsed_result.error_message,
            artifacts={"runner_output": "runner_output.log"},
        )
    if parsed_result.result is None:
        return JobResult.failure(
            error_kind="runner_error",
            error_message="code execution returned neither a result nor a protocol failure",
        )
    result = _code_result(parsed_result.result)
    artifacts = dict(result.artifacts)
    artifacts["runner_output"] = "runner_output.log"
    return JobResult(
        status=result.status,
        elapsed_ms=result.elapsed_ms,
        error_kind=result.error_kind,
        error_message=result.error_message,
        final_url=result.final_url,
        title=result.title,
        artifacts=artifacts,
    )


async def _run_code_job(*, config: RunnerConfig, job: RunnerJob) -> JobResult:
    if job.source_relpath is None:
        return JobResult.failure(
            error_kind="missing_source",
            error_message="source_relpath is required for code tests",
        )
    directory_outcome = await _prepare_output_directory(config=config, job=job)
    if isinstance(directory_outcome, JobResult):
        return directory_outcome
    output_directory = directory_outcome
    source_outcome = await stage_verified_source(
        tests_dir=config.tests_dir,
        source_relpath=job.source_relpath,
        expected_sha256=job.source_sha256,
        staging_dir=output_directory,
        prepared_staging_directory=True,
    )
    if isinstance(source_outcome, SourceIntegrityFailure):
        return JobResult.failure(
            error_kind=source_outcome.error_kind,
            error_message=source_outcome.error_message,
        )
    verified_source = source_outcome

    execution = await run_code_local(
        request=CodeExecutionRequest(
            kind=job.test_kind,
            test_file=verified_source.staged_path,
            base_url=job.base_url,
            artifacts_dir=output_directory,
            timeout_seconds=job.timeout_seconds,
            trace_on_failure=config.trace_on_failure,
            trusted_credentials=trusted_code_test_environment(
                config=config,
                job=job,
                verified_source=verified_source,
            ),
        ),
    )
    output_log_path = output_directory / "runner_output.log"
    try:
        await asyncio.to_thread(
            replace_private_file,
            output_log_path,
            f"{execution.combined_output}\n".encode(errors="replace"),
        )
    except (ArtifactStorageError, OSError):
        return JobResult.failure(
            error_kind="runner_output_write_failed",
            error_message=f"could not write runner output artifact: {output_log_path}",
        )
    return _finalize_code_result(execution)


async def execute_job(browser: Browser | None, config: RunnerConfig, job: RunnerJob) -> JobResult:
    """Execute one claimed job through its declared backend.

    Returns:
        A normalized result ready for registry completion.
    """
    if job.test_kind == "stepflow":
        directory_outcome = await _prepare_output_directory(config=config, job=job)
        if isinstance(directory_outcome, JobResult):
            return directory_outcome
        output_directory = directory_outcome
        return await run_stepflow(
            browser=browser,
            config=config,
            job=job,
            artifacts_dir=output_directory,
        )
    if job.test_kind in _CODE_TEST_KINDS:
        return await _run_code_job(config=config, job=job)
    return JobResult.failure(
        error_kind="invalid_kind",
        error_message=f"unsupported test kind: {job.test_kind}",
    )
