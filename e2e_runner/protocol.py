# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed HTTP protocol used by E2E runners."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from e2e_registry.models import require_json_object
from e2e_runner.models import RunnerJob

if TYPE_CHECKING:
    import httpx

    from e2e_registry.models import JsonObject, UntrustedJsonValue
    from e2e_runner.models import RunnerConfig


class RegistryProtocolError(ValueError):
    """Raised when the registry returns a malformed runner response."""


async def claim_jobs(client: httpx.AsyncClient, config: RunnerConfig) -> list[RunnerJob]:
    """Claim and validate one bounded batch of jobs.

    Returns:
        Validated jobs owned by this runner.

    Raises:
        RegistryProtocolError: If the registry response is not a jobs collection.
    """
    response = await client.post(
        f"{config.registry_base_url.rstrip('/')}/api/v1/runner/claim",
        headers={"Authorization": f"Bearer {config.runner_token}"},
        json={"max_runs": config.concurrency},
        timeout=20.0,
    )
    _ = response.raise_for_status()
    decoded = cast("UntrustedJsonValue", json.loads(response.text))
    body = require_json_object(decoded, label="runner claim response")
    raw_jobs = body.get("jobs")
    if not isinstance(raw_jobs, list):
        message = "runner claim response.jobs must be a list"
        raise RegistryProtocolError(message)

    jobs: list[RunnerJob] = []
    for index, raw_job in enumerate(raw_jobs):
        payload = require_json_object(raw_job, label=f"runner claim response.jobs[{index}]")
        jobs.append(RunnerJob.from_json(payload))
    return jobs


async def complete_job(
    client: httpx.AsyncClient,
    config: RunnerConfig,
    *,
    run_id: str,
    payload: JsonObject,
) -> None:
    """Submit one terminal job result to the registry."""
    response = await client.post(
        f"{config.registry_base_url.rstrip('/')}/api/v1/runner/runs/{run_id}/complete",
        headers={"Authorization": f"Bearer {config.runner_token}"},
        json=payload,
        timeout=30.0,
    )
    _ = response.raise_for_status()
