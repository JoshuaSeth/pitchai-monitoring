# Copyright (c) 2026 PitchAI. All rights reserved.
"""Concurrent E2E runner service loop."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, NamedTuple

from httpx import HTTPError
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from e2e_runner.browser import launch_browser
from e2e_runner.http_gateway import registry_http_client
from e2e_runner.jobs import execute_job
from e2e_runner.protocol import claim_jobs, complete_job

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import httpx
    from playwright.async_api import Browser, Playwright

    from e2e_runner.models import JobResult, RunnerConfig, RunnerJob

    type JobExecutor = Callable[[Browser | None, RunnerConfig, RunnerJob], Awaitable[JobResult]]

LOGGER = logging.getLogger("e2e-runner")


class ExecutionEnvelope(NamedTuple):
    """One result with timestamps scoped to its own execution coroutine."""

    result: JobResult
    started_at_ts: float
    finished_at_ts: float


class CompletionOutcome(NamedTuple):
    """Result of one independent registry-completion request."""

    succeeded: bool
    error_message: str | None


async def execute_timed_job(
    *,
    browser: Browser | None,
    config: RunnerConfig,
    job: RunnerJob,
    executor: JobExecutor,
) -> ExecutionEnvelope:
    """Execute one job and preserve its exact wall-clock interval.

    Returns:
        The executor result with its per-job timestamps.
    """
    started_at_ts = time.time()
    result = await executor(browser, config, job)
    finished_at_ts = time.time()
    return ExecutionEnvelope(
        result=result,
        started_at_ts=started_at_ts,
        finished_at_ts=finished_at_ts,
    )


async def _browser_for_batch(playwright: Playwright, jobs: list[RunnerJob]) -> Browser | None:
    if not any(job.test_kind == "stepflow" for job in jobs):
        return None
    try:
        return await launch_browser(playwright)
    except (OSError, PlaywrightError):
        LOGGER.exception(
            "Chromium launch failed; StepFlow jobs will report infrastructure degradation",
        )
        return None


async def _close_browser(browser: Browser | None) -> None:
    if browser is None:
        return
    try:
        await browser.close()
    except (OSError, PlaywrightError):
        LOGGER.exception("Chromium close failed")


async def _complete_one(
    *,
    client: httpx.AsyncClient,
    config: RunnerConfig,
    job: RunnerJob,
    envelope: ExecutionEnvelope,
) -> CompletionOutcome:
    payload = envelope.result.completion_payload(
        started_at_ts=envelope.started_at_ts,
        finished_at_ts=envelope.finished_at_ts,
    )
    try:
        await complete_job(client, config, run_id=job.run_id, payload=payload)
    except HTTPError as error:
        return CompletionOutcome(succeeded=False, error_message=str(error))
    return CompletionOutcome(succeeded=True, error_message=None)


async def _execute_batch(
    *,
    client: httpx.AsyncClient,
    config: RunnerConfig,
    jobs: list[RunnerJob],
    playwright: Playwright,
) -> int:
    browser = await _browser_for_batch(playwright, jobs)
    execution_envelopes = await asyncio.gather(
        *(
            execute_timed_job(
                browser=browser if job.test_kind == "stepflow" else None,
                config=config,
                job=job,
                executor=execute_job,
            )
            for job in jobs
        ),
    )
    completion_outcomes = await asyncio.gather(
        *(
            _complete_one(
                client=client,
                config=config,
                job=job,
                envelope=envelope,
            )
            for job, envelope in zip(jobs, execution_envelopes, strict=True)
        ),
    )
    await _close_browser(browser)

    failed_completions = 0
    for job, outcome in zip(jobs, completion_outcomes, strict=True):
        if not outcome.succeeded:
            failed_completions += 1
            LOGGER.error(
                "Completion failed run_id=%s test_id=%s: %s",
                job.run_id,
                job.test_id,
                outcome.error_message,
            )
        else:
            LOGGER.info("Job complete run_id=%s test_id=%s", job.run_id, job.test_id)
    return failed_completions


async def run_once(config: RunnerConfig) -> int:
    """Claim and execute at most one batch.

    Returns:
        Zero when every claimed result was completed; otherwise one.
    """
    async with registry_http_client() as client:
        jobs = await claim_jobs(client, config)
        if not jobs:
            LOGGER.info("No jobs claimed; exiting --once")
            return 0
        LOGGER.info("Claimed jobs count=%s", len(jobs))
        async with async_playwright() as playwright:
            failed_completions = await _execute_batch(
                client=client,
                config=config,
                jobs=jobs,
                playwright=playwright,
            )
    return int(failed_completions > 0)


async def run_forever(config: RunnerConfig) -> None:
    """Continuously claim and execute registry work until cancelled."""
    LOGGER.info(
        "Starting e2e-runner registry_base_url=%s poll_seconds=%s concurrency=%s tests_dir=%s",
        config.registry_base_url,
        config.poll_seconds,
        config.concurrency,
        config.tests_dir,
    )
    async with (
        registry_http_client() as client,
        async_playwright() as playwright,
    ):
        while True:
            jobs = await claim_jobs(client, config)
            if jobs:
                LOGGER.info("Claimed jobs count=%s", len(jobs))
                _ = await _execute_batch(
                    client=client,
                    config=config,
                    jobs=jobs,
                    playwright=playwright,
                )
                continue
            await asyncio.sleep(config.poll_seconds)
