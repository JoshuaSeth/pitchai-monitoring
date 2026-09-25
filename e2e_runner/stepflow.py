# Copyright (c) 2026 PitchAI. All rights reserved.
"""StepFlow execution adapter for registry jobs."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from domain_checks.metrics_synthetic import run_synthetic_transactions
from e2e_runner.models import JobResult

if TYPE_CHECKING:
    from pathlib import Path

    from playwright.async_api import Browser

    from domain_checks.types import JsonObject as DomainJsonObject
    from e2e_registry.models import JsonObject, JsonValue
    from e2e_runner.models import RunnerConfig, RunnerJob

_ARTIFACT_KEYS = ("failure_screenshot", "trace_zip", "run_log")


def _text_value(value: JsonValue) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _artifact_names(details: JsonObject) -> JsonObject:
    artifacts: JsonObject = {}
    for key, raw_value in details.items():
        is_named_artifact = key in _ARTIFACT_KEYS or key.startswith("screenshot_")
        value = _text_value(raw_value)
        if is_named_artifact and value is not None:
            artifacts[key] = value
    return artifacts


async def run_stepflow(
    *,
    browser: Browser | None,
    config: RunnerConfig,
    job: RunnerJob,
    artifacts_dir: Path,
) -> JobResult:
    """Execute one StepFlow job through the domain synthetic engine.

    Returns:
        A normalized job result.
    """
    if browser is None:
        return JobResult.infrastructure_failure(
            error_kind="browser_unavailable",
            error_message="runner has no browser instance",
        )
    if not job.definition:
        return JobResult.failure(
            error_kind="invalid_definition",
            error_message="definition must be a non-empty object",
        )

    transaction = cast("DomainJsonObject", job.definition)
    results = await run_synthetic_transactions(
        domain=job.test_id,
        base_url=job.base_url,
        browser=browser,
        transactions=[transaction],
        timeout_seconds=job.timeout_seconds,
        artifacts_dir=str(artifacts_dir),
        trace_on_failure=config.trace_on_failure,
    )
    result = results[0] if results else None
    if result is None:
        return JobResult.failure(error_kind="runner_error", error_message="StepFlow produced no result")

    details = cast("JsonObject", result.details)
    if result.ok:
        return JobResult(
            status="pass",
            elapsed_ms=result.elapsed_ms,
            final_url=_text_value(details.get("final_url")),
            title=_text_value(details.get("title")),
        )
    status = "infra_degraded" if result.browser_infra_error else "fail"
    error_kind = "browser_infra_error" if result.browser_infra_error else "assertion_failed"
    return JobResult(
        status=status,
        elapsed_ms=result.elapsed_ms,
        error_kind=error_kind,
        error_message=result.error,
        final_url=_text_value(details.get("final_url")),
        title=_text_value(details.get("title")),
        artifacts=_artifact_names(details),
    )
