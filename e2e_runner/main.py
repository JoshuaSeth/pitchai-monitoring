# Copyright (c) 2026 PitchAI. All rights reserved.
"""Native E2E runner entry point with retained heartbeat instrumentation hooks."""

from __future__ import annotations

import argparse
import logging
import os
from typing import TYPE_CHECKING, cast

import anyio
from playwright.async_api import async_playwright

from .browser import BrowserLease
from .browser import launch_browser as _launch_browser
from .config import RunnerConfig, load_config
from .cycle import RunnerCycle, RunnerHooks
from .job import run_one_job as _run_one_job
from .transport import RegistryHttpClient
from .transport import claim_jobs as _claim_jobs

if TYPE_CHECKING:
    from typing import NoReturn

LOGGER = logging.getLogger("e2e-runner")
__all__ = ["RunnerConfig", "load_config", "main", "run_loop"]


async def run_loop(cfg: RunnerConfig) -> NoReturn:
    """Keep native HTTP/Playwright ownership around the installed claim and job hooks.

    Raises:
        RuntimeError: The required registry token is missing.
    """
    if not cfg.runner_token:
        message = "Missing E2E_REGISTRY_RUNNER_TOKEN"
        raise RuntimeError(message)
    LOGGER.info(
        "Starting e2e-runner registry_base_url=%s poll_seconds=%s concurrency=%s "
        "trace_on_failure=%s tests_dir=%s code_exec_mode=%s",
        cfg.registry_base_url, cfg.poll_seconds, cfg.concurrency,
        cfg.trace_on_failure, cfg.tests_dir, cfg.code_exec_mode,
    )
    async with RegistryHttpClient() as client, async_playwright() as playwright:
        lease = BrowserLease(_launch_browser)
        cycle = RunnerCycle(cfg, client, RunnerHooks(_claim_jobs, _run_one_job))
        try:
            await cycle.poll(playwright, lease)
        finally:
            await lease.close()


async def run_once(cfg: RunnerConfig) -> None:
    """Retain claim-before-browser ordering and the smoke path's original error propagation."""
    async with RegistryHttpClient() as client:
        hooks = RunnerHooks(_claim_jobs, _run_one_job)
        jobs = await hooks.claim(client, cfg)
        if not jobs:
            LOGGER.info("No jobs claimed; exiting --once")
            return
        async with async_playwright() as playwright:
            await RunnerCycle(cfg, client, hooks).once(playwright, jobs, BrowserLease(_launch_browser))


def main() -> None:
    """Parse native CLI options and own one asyncio-backed application run."""
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--once", action="store_true", help="Run a single claim+execute loop then exit")
    args = parser.parse_args()
    level = (os.getenv("E2E_RUNNER_LOG_LEVEL") or os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    logging.basicConfig(level=cast("int | str", getattr(logging, level, logging.INFO)),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = load_config()
    if cast("bool", args.once):
        anyio.run(run_once, cfg)
        return
    anyio.run(run_loop, cfg)


if __name__ == "__main__":
    main()
