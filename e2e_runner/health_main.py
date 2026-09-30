# Copyright (c) 2026 PitchAI. All rights reserved.
"""Run the established E2E worker with a liveness heartbeat installed."""

from __future__ import annotations

import asyncio
import os
from functools import partial
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, cast

from .heartbeat import RunnerHeartbeat, narrow_test_id, start_heartbeat_publisher

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from httpx import AsyncClient

    from .heartbeat import JobValue
    from .main import RunnerConfig

_DEFAULT_HEARTBEAT_PATH = "/run/pitchai-health/e2e-runner-heartbeat.json"
_DEFAULT_HEARTBEAT_SECONDS = 5.0
_MINIMUM_HEARTBEAT_SECONDS = 1.0


class RunnerBrowser(NamedTuple):
    """Browser handle the runner loop owns and passes through unread.

    The runner image resolves the browser library, so this boundary names the
    handle instead of importing a dependency the quality gate does not install.
    """


class _RunnerModule(NamedTuple):
    main: object


_RUNNER = cast("_RunnerModule", cast("object", import_module("e2e_runner.main")))
_RUNNER_MAIN = cast("Callable[[], None]", _RUNNER.main)
_RUNNER_NAMESPACE = cast("dict[str, object]", vars(cast("object", _RUNNER)))


def heartbeat_path() -> Path:
    """Return the heartbeat document path configured for this container."""
    raw = os.getenv("E2E_RUNNER_HEARTBEAT_PATH", "").strip()
    return Path(raw or _DEFAULT_HEARTBEAT_PATH)


def heartbeat_seconds() -> float:
    """Return the heartbeat publish cadence configured for this container."""
    raw = os.getenv("E2E_RUNNER_HEARTBEAT_SECONDS", "").strip()
    configured = float(raw) if raw else _DEFAULT_HEARTBEAT_SECONDS
    return max(_MINIMUM_HEARTBEAT_SECONDS, configured)


def _record_claim_outcome(
    heartbeat: RunnerHeartbeat,
    claim: asyncio.Future[Sequence[Mapping[str, JobValue]]],
) -> None:
    """Record the outcome of one completed claim task.

    The completed-task callback is the instrumentation edge that observes the
    claim result: a failed claim keeps its original exception and traceback for
    the loop, while the heartbeat retains only the narrow failure class.

    Args:
        heartbeat: Record updated with the claim outcome.
        claim: Completed claim task owned by the instrumented loop.
    """
    if claim.cancelled():
        heartbeat.record_claim_error(error_class=asyncio.CancelledError.__name__)
        return
    failure = claim.exception()
    if failure is None:
        heartbeat.record_claim_success()
    else:
        heartbeat.record_claim_error(error_class=type(failure).__name__)


def install_instrumentation(heartbeat: RunnerHeartbeat) -> None:
    """Record claim and job progress around the runner's own loop hooks.

    Args:
        heartbeat: Record updated from the runner loop.
    """
    original_claim = cast(
        "Callable[[AsyncClient, RunnerConfig], Awaitable[Sequence[Mapping[str, JobValue]]]]",
        _RUNNER_NAMESPACE["_claim_jobs"],
    )
    original_job = cast(
        "Callable[[RunnerBrowser | None, RunnerConfig, AsyncClient, Mapping[str, JobValue]], Awaitable[None]]",
        _RUNNER_NAMESPACE["_run_one_job"],
    )

    async def claim_with_heartbeat(
        client: AsyncClient,
        config: RunnerConfig,
    ) -> Sequence[Mapping[str, JobValue]]:
        heartbeat.record_claim_attempt()
        claim = asyncio.ensure_future(original_claim(client, config))
        claim.add_done_callback(partial(_record_claim_outcome, heartbeat))
        return await claim

    async def job_with_heartbeat(
        browser: RunnerBrowser | None,
        config: RunnerConfig,
        client: AsyncClient,
        job: Mapping[str, JobValue],
    ) -> None:
        heartbeat.record_job_start(test_id=narrow_test_id(job.get("test_id")))
        try:
            await original_job(browser, config, client, job)
        finally:
            heartbeat.record_job_finish()

    _RUNNER_NAMESPACE["_claim_jobs"] = claim_with_heartbeat
    _RUNNER_NAMESPACE["_run_one_job"] = job_with_heartbeat


def main() -> None:
    """Start the heartbeat publisher and hand control to the runner loop."""
    heartbeat = RunnerHeartbeat(path=heartbeat_path())
    _ = start_heartbeat_publisher(heartbeat=heartbeat, interval_seconds=heartbeat_seconds())
    install_instrumentation(heartbeat)
    heartbeat.write()
    _RUNNER_MAIN()


if __name__ == "__main__":
    heartbeat_path().parent.mkdir(parents=True, exist_ok=True)
    main()
