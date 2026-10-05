# Copyright (c) 2026 PitchAI. All rights reserved.
"""Runner claim and completion HTTP boundaries with unchanged transaction order."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Annotated, cast

import fastapi

from . import auth as registry_auth
from . import db as dbm
from . import schema
from .app_context import RegistryContext
from .runner_notifications import RunnerNotifications
from .runner_transport import RegistryHttpClient

if TYPE_CHECKING:
    from domain_checks.config_values import ConfigValue

    from .dashboard_records import Record

router = fastapi.APIRouter()
RunnerClaimRequest = schema.RunnerClaimRequest
RunnerCompleteRequest = schema.RunnerCompleteRequest


def claimed_job(claim: dbm.ClaimedRun) -> Record:
    """Select the existing eleven job fields without adding internal data.

    Returns:
        The runner's original job object.
    """
    return {
        "run_id": claim.run_id, "test_id": claim.test_id, "tenant_id": claim.tenant_id,
        "test_name": claim.test_name, "base_url": claim.base_url, "timeout_seconds": claim.timeout_seconds,
        "test_kind": claim.test_kind, "definition": cast("Record", claim.definition),
        "source_relpath": claim.source_relpath, "source_filename": claim.source_filename,
        "source_sha256": claim.source_sha256,
    }


@router.post("/api/v1/runner/claim", response_model=dict)
async def runner_claim(
    request: fastapi.Request,
    _auth: Annotated[None, fastapi.Depends(registry_auth.require_runner)],
    req: RunnerClaimRequest | None = None,
) -> Record:
    """Claim due work only after the existing runner authentication dependency.

    Returns:
        The original success envelope and ordered job list.
    """
    context = RegistryContext(cast("fastapi.FastAPI", request.app))
    claimed = await asyncio.to_thread(dbm.claim_due_runs, context.settings, max_runs=int(req.max_runs) if req else 1)
    jobs: list[ConfigValue] = [claimed_job(claim) for claim in claimed]
    return {"ok": True, "jobs": jobs}


@router.post("/api/v1/runner/runs/{run_id}/complete", response_model=dict)
async def runner_complete(
    request: fastapi.Request, run_id: str,
    _auth: Annotated[None, fastapi.Depends(registry_auth.require_runner)],
    req: RunnerCompleteRequest | None = None,
) -> Record:
    """Commit completion before opening the existing alert transport context.

    Returns:
        The unchanged completion outcome envelope.

    Raises:
        HTTPException: The body or completion status is invalid.
    """
    if req is None:
        raise fastapi.HTTPException(status_code=400, detail="missing_body")
    status = str(req.status or "").strip().lower()
    if status not in {"pass", "fail", "infra_degraded"}:
        raise fastapi.HTTPException(status_code=400, detail="invalid_status")
    context = RegistryContext(cast("fastapi.FastAPI", request.app))
    completion = dbm.RunCompletion(
        status=status, elapsed_ms=req.elapsed_ms, error_kind=req.error_kind, error_message=req.error_message,
        final_url=req.final_url, title=req.title, artifacts=req.artifacts or {},
        started_at_ts=req.started_at_ts, finished_at_ts=req.finished_at_ts,
    )
    outcome = await asyncio.to_thread(dbm.complete_run, context.settings, run_id=run_id, completion=completion)
    notifications = RunnerNotifications(context, run_id, req, outcome)
    async with RegistryHttpClient() as client:
        await notifications.failure(client)
        await notifications.recovery(client)
    return {"ok": True, "outcome": cast("Record", outcome.__dict__)}
