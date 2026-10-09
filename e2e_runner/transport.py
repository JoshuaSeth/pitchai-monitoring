# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing authenticated registry claim and completion request contracts."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from httpx import AsyncClient

if TYPE_CHECKING:
    from domain_checks.event_bus_delivery import JsonObject, JsonValue

    from .config import RunnerConfig


class RegistryHttpClient(AsyncClient):
    """Own the native registry session defaults and inherited context lifetime."""

    def __init__(self) -> None:
        """Install the original runner User-Agent without changing native HTTP defaults."""
        super().__init__(headers={"User-Agent": "PitchAI E2E Runner"})


async def claim_jobs(client: AsyncClient, cfg: RunnerConfig) -> list[JsonValue]:
    """Return the registry's job list unchanged; filtering remains in the loop."""
    response = await client.post(
        f"{cfg.registry_base_url.rstrip('/')}/api/v1/runner/claim",
        headers={"Authorization": f"Bearer {cfg.runner_token}"},
        json={"max_runs": int(cfg.concurrency)}, timeout=20.0,
    )
    response.raise_for_status()
    data = cast("JsonValue", response.json())
    jobs = data.get("jobs") if isinstance(data, dict) else None
    return jobs if isinstance(jobs, list) else []


async def complete_job(client: AsyncClient, cfg: RunnerConfig, *, run_id: str, payload: JsonObject) -> None:
    """Report every completed job, including degraded results, and propagate send failures."""
    response = await client.post(
        f"{cfg.registry_base_url.rstrip('/')}/api/v1/runner/runs/{run_id}/complete",
        headers={"Authorization": f"Bearer {cfg.runner_token}"}, json=payload, timeout=30.0,
    )
    response.raise_for_status()
