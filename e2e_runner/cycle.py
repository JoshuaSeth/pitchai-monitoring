# Copyright (c) 2026 PitchAI. All rights reserved.
"""Claim/execution ordering around the native runner's installed heartbeat hooks."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from domain_checks.browser_failure import BrowserFailure

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from typing import NoReturn

    from httpx import AsyncClient
    from playwright.async_api import Browser, Playwright

    from domain_checks.event_bus_delivery import JsonObject, JsonValue

    from .browser import BrowserLease
    from .config import RunnerConfig

LOGGER = logging.getLogger("e2e-runner")
type Claim = Callable[[AsyncClient, RunnerConfig], Awaitable[list[JsonValue]]]
type Execute = Callable[[Browser | None, RunnerConfig, AsyncClient, JsonObject], Awaitable[None]]


def job_kind(job: JsonObject) -> str:
    """Return the original blank/default/lowercase kind normalization."""
    return str(job.get("test_kind") or "stepflow").strip().lower() or "stepflow"


def needs_browser(jobs: list[JsonValue]) -> bool:
    """Return whether any accepted dictionary job requires StepFlow Chromium."""
    return any(isinstance(job, dict) and job_kind(job) == "stepflow" for job in jobs)


@dataclass(frozen=True)
class RunnerHooks:
    """Capture the currently installed public claim/job instrumentation at entry."""

    claim: Claim
    execute: Execute


@dataclass(frozen=True)
class RunnerCycle:
    """Preserve claim failures, admission and sequential job completion in one iteration."""

    cfg: RunnerConfig
    client: AsyncClient
    hooks: RunnerHooks

    async def iterate(self, playwright: Playwright, lease: BrowserLease) -> None:
        """Run one native polling cycle without consuming cancellation."""
        jobs: list[JsonValue] = []
        with BrowserFailure() as failure:
            jobs = await self.hooks.claim(self.client, self.cfg)
            if jobs:
                LOGGER.info("Claimed jobs count=%s", len(jobs))
        if failure.error is not None:
            LOGGER.error("Claim failed", exc_info=failure.error)
            jobs = []
        if not jobs:
            await asyncio.sleep(self.cfg.poll_seconds)
            return
        browser = await lease.ensure(playwright, time.time()) if needs_browser(jobs) else None
        for job in jobs:
            if isinstance(job, dict):
                await self._ordinary_job(browser, job)

    async def poll(self, playwright: Playwright, lease: BrowserLease) -> NoReturn:
        """Continue polling until the existing cancellation or fatal boundary exits."""
        while True:
            await self.iterate(playwright, lease)

    async def _ordinary_job(self, browser: Browser | None, job: JsonObject) -> None:
        """Log one ordinary job failure and continue to later jobs."""
        with BrowserFailure() as failure:
            await self.hooks.execute(browser if job_kind(job) == "stepflow" else None, self.cfg, self.client, job)
            run_id = str(job.get("run_id") or "").strip()
            test_id = str(job.get("test_id") or "").strip()
            LOGGER.info("Job complete run_id=%s test_id=%s", run_id, test_id)
        if failure.error is not None:
            run_id = str(job.get("run_id") or "").strip()
            test_id = str(job.get("test_id") or "").strip()
            LOGGER.error("Job crashed run_id=%s test_id=%s", run_id, test_id, exc_info=failure.error)

    async def once(self, playwright: Playwright, jobs: list[JsonValue], lease: BrowserLease) -> None:
        """Run smoke-mode jobs, preserving its unsuppressed job and close errors."""
        browser = None
        if needs_browser(jobs):
            with BrowserFailure() as failure:
                browser = await lease.launch(playwright)
            if failure.error is not None:
                LOGGER.warning("Chromium launch failed in --once; StepFlow jobs will be infra_degraded")
        try:
            await self._once_jobs(browser, jobs)
        finally:
            if browser is not None:
                await browser.close()

    async def _once_jobs(self, browser: Browser | None, jobs: list[JsonValue]) -> None:
        """Execute smoke jobs sequentially, retaining their unsuppressed failure boundary."""
        for job in jobs:
            if isinstance(job, dict):
                await self.hooks.execute(browser if job_kind(job) == "stepflow" else None,
                                         self.cfg, self.client, job)
