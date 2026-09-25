# Copyright (c) 2026 PitchAI. All rights reserved.
"""Runner claim and completion API routes."""

from __future__ import annotations

import asyncio
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from httpx import AsyncClient

from e2e_registry import db as dbm
from e2e_registry.app_context import context_from_request
from e2e_registry.auth import require_runner
from e2e_registry.models import JsonObject
from e2e_registry.runner_notifications import send_failure_notifications, send_recovery_notification
from e2e_registry.schema import RunnerClaimRequest, RunnerCompleteRequest

router = APIRouter()
_RUNTIME_ANNOTATIONS = (
    Request,
    AsyncClient,
    JsonObject,
    RunnerClaimRequest,
    RunnerCompleteRequest,
)


@router.post("/api/v1/runner/claim")
async def runner_claim(
    request: Request,
    _auth: Annotated[None, Depends(require_runner)],
    body: RunnerClaimRequest | None = None,
) -> JsonObject:
    """Claim due jobs for an authenticated runner.

    Returns:
        The bounded batch of claimed jobs.
    """
    context = context_from_request(request)
    max_runs = int(body.max_runs) if body is not None else 1
    claimed = await asyncio.to_thread(dbm.claim_due_runs, context.settings, max_runs=max_runs)
    jobs: list[JsonObject] = [
        {
            "run_id": claim.run_id,
            "test_id": claim.test_id,
            "tenant_id": claim.tenant_id,
            "test_name": claim.test_name,
            "base_url": claim.base_url,
            "timeout_seconds": claim.timeout_seconds,
            "test_kind": claim.test_kind,
            "definition": claim.definition,
            "source_relpath": claim.source_relpath,
            "source_filename": claim.source_filename,
            "source_sha256": claim.source_sha256,
        }
        for claim in claimed
    ]
    return cast("JsonObject", {"ok": True, "jobs": jobs})


@router.post("/api/v1/runner/runs/{run_id}/complete")
async def runner_complete(
    request: Request,
    run_id: str,
    _auth: Annotated[None, Depends(require_runner)],
    body: RunnerCompleteRequest | None = None,
) -> JsonObject:
    """Accept one authenticated runner completion and emit transitions.

    Returns:
        The accepted completion transition.

    Raises:
        HTTPException: If the completion body or status is invalid.
    """
    if body is None:
        raise HTTPException(status_code=400, detail="missing_body")
    status = str(body.status or "").strip().lower()
    if status not in {"pass", "fail", "infra_degraded"}:
        raise HTTPException(status_code=400, detail="invalid_status")
    context = context_from_request(request)
    completion = dbm.RunCompletion(
        status=status,
        elapsed_ms=body.elapsed_ms,
        error_kind=body.error_kind,
        error_message=body.error_message,
        final_url=body.final_url,
        title=body.title,
        artifacts=body.artifacts,
        started_at_ts=body.started_at_ts,
        finished_at_ts=body.finished_at_ts,
    )
    outcome = await asyncio.to_thread(
        dbm.complete_run,
        context.settings,
        run_id=run_id,
        completion=completion,
    )
    async with AsyncClient(headers={"User-Agent": "PitchAI E2E Registry"}) as http_client:
        if outcome.alerted_down:
            await send_failure_notifications(
                context=context,
                http_client=http_client,
                run_id=run_id,
                body=body,
                outcome=outcome,
            )
        if outcome.recovered_up:
            await send_recovery_notification(
                context=context,
                http_client=http_client,
                run_id=run_id,
                outcome=outcome,
            )
    outcome_payload = cast("JsonObject", outcome._asdict())
    return cast("JsonObject", {"ok": True, "outcome": outcome_payload})
