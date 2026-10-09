# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tenant test creation with the original URL/StepFlow admission sequence."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Annotated, cast

import fastapi

from . import auth as registry_auth
from . import db as dbm
from . import schema
from .app_context import RegistryContext
from .app_host_policy import RegistryHostPolicy
from .stepflow import StepFlowValidationError, validate_definition

if TYPE_CHECKING:
    from .dashboard_records import Record

router = fastapi.APIRouter()
CreateTestRequest = schema.CreateTestRequest


def _validated_creation(policy: RegistryHostPolicy, body: CreateTestRequest) -> tuple[str, Record]:
    base = policy.validate_base_url(body.base_url)
    definition = cast("Record", validate_definition(cast("Record", body.definition)))
    return base, definition


@router.post("/api/v1/tests", response_model=dict)
async def api_create_test(
    request: fastapi.Request,
    auth: Annotated[registry_auth.RequestAuth, fastapi.Depends(registry_auth.require_tenant_auth)],
    req: CreateTestRequest | None = None,
) -> Record:
    """Validate the original base URL and StepFlow before inserting the tenant test.

    Returns:
        The existing success/test envelope.

    Raises:
        HTTPException: The body or StepFlow is invalid.
    """
    if req is None:
        raise fastapi.HTTPException(status_code=400, detail="missing_body")
    context = RegistryContext(cast("fastapi.FastAPI", request.app))
    try:
        base, definition = _validated_creation(RegistryHostPolicy(context), req)
    except StepFlowValidationError as exc:
        raise fastapi.HTTPException(status_code=400, detail=str(exc)) from exc
    created = cast("Record", await asyncio.to_thread(
        dbm.insert_test, context.settings, tenant_id=auth.tenant_id, name=req.name,
        base_url=base, test_kind="stepflow", definition=definition,
        interval_seconds=req.interval_seconds, timeout_seconds=req.timeout_seconds,
        jitter_seconds=req.jitter_seconds, down_after_failures=req.down_after_failures,
        up_after_successes=req.up_after_successes, notify_on_recovery=bool(req.notify_on_recovery),
        dispatch_on_failure=bool(req.dispatch_on_failure),
    ))
    return {"ok": True, "test": created}
