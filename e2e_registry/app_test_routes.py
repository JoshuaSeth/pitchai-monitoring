# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tenant-scoped test lookup and mutation HTTP boundaries."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Annotated, cast

import fastapi

from . import auth as registry_auth
from . import db as dbm
from . import schema
from .app_context import RegistryContext
from .app_host_policy import RegistryHostPolicy
from .disablement import parse_disabled_until
from .stepflow import validate_definition

if TYPE_CHECKING:
    from domain_checks.config_values import ConfigValue

    from .dashboard_records import Record

# Lookup and mutation insertion points retain order around source-upload routes.
lookup_router = fastapi.APIRouter()
router = fastapi.APIRouter()
PatchTestRequest = schema.PatchTestRequest
DisableTestRequest = schema.DisableTestRequest


@lookup_router.get("/api/v1/tests", response_model=dict)
async def api_list_tests(
    request: fastapi.Request,
    auth: Annotated[registry_auth.RequestAuth, fastapi.Depends(registry_auth.require_tenant_auth)],
) -> Record:
    """List the authenticated tenant's tests.

    Returns:
        The existing success/list envelope.
    """
    context = RegistryContext(cast("fastapi.FastAPI", request.app))
    tests = cast("list[ConfigValue]", await asyncio.to_thread(
        dbm.list_tests, context.settings, tenant_id=auth.tenant_id,
    ))
    return {"ok": True, "tests": tests}


@lookup_router.get("/api/v1/tests/{test_id}", response_model=dict)
async def api_get_test(
    request: fastapi.Request, test_id: str,
    auth: Annotated[registry_auth.RequestAuth, fastapi.Depends(registry_auth.require_tenant_auth)],
) -> Record:
    """Read one tenant-scoped test.

    Returns:
        The existing success/test envelope.

    Raises:
        HTTPException: The database returns no test.
    """
    context = RegistryContext(cast("fastapi.FastAPI", request.app))
    test = cast("Record | None", await asyncio.to_thread(
        dbm.get_test, context.settings, tenant_id=auth.tenant_id, test_id=test_id,
    ))
    if not test:
        raise fastapi.HTTPException(status_code=404, detail="not_found")
    return {"ok": True, "test": test}


@router.patch("/api/v1/tests/{test_id}", response_model=dict)
async def api_patch_test(
    request: fastapi.Request, test_id: str,
    auth: Annotated[registry_auth.RequestAuth, fastapi.Depends(registry_auth.require_tenant_auth)],
    req: PatchTestRequest | None = None,
) -> Record:
    """Preserve explicit nulls, validation order and write-then-read behavior.

    Returns:
        The success envelope and the database's post-write test.

    Raises:
        HTTPException: The body is absent or no matching test was updated.
    """
    if req is None:
        raise fastapi.HTTPException(status_code=400, detail="missing_body")
    context = RegistryContext(cast("fastapi.FastAPI", request.app))
    changes = cast("Record", req.model_dump(exclude_unset=True))
    if "base_url" in changes and changes["base_url"] is not None:
        changes["base_url"] = RegistryHostPolicy(context).validate_base_url(cast("str", changes["base_url"]))
    if "definition" in changes and changes["definition"] is not None:
        changes["definition"] = cast("Record", validate_definition(cast("Record", changes["definition"])))
    updated = await asyncio.to_thread(
        dbm.patch_test, context.settings, tenant_id=auth.tenant_id, test_id=test_id, patch=changes,
    )
    if not updated:
        raise fastapi.HTTPException(status_code=404, detail="not_found")
    test = cast("Record | None", await asyncio.to_thread(
        dbm.get_test, context.settings, tenant_id=auth.tenant_id, test_id=test_id,
    ))
    return {"ok": True, "test": test}


@router.post("/api/v1/tests/{test_id}/disable", response_model=dict)
async def api_disable_test(
    request: fastapi.Request, test_id: str,
    auth: Annotated[registry_auth.RequestAuth, fastapi.Depends(registry_auth.require_tenant_auth)],
    req: DisableTestRequest | None = None,
) -> Record:
    """Parse the requested disablement time before making the original scoped write.

    Returns:
        The existing success envelope.

    Raises:
        HTTPException: The body/time is invalid or no test was updated.
    """
    if req is None:
        raise fastapi.HTTPException(status_code=400, detail="missing_body")
    try:
        until_ts = parse_disabled_until(req.until)
    except ValueError as exc:
        raise fastapi.HTTPException(status_code=400, detail=f"invalid_until: {exc}") from exc
    context = RegistryContext(cast("fastapi.FastAPI", request.app))
    updated = await asyncio.to_thread(
        dbm.set_test_disabled, context.settings, tenant_id=auth.tenant_id, test_id=test_id,
        disabled=True, reason=req.reason, until_ts=until_ts,
    )
    if not updated:
        raise fastapi.HTTPException(status_code=404, detail="not_found")
    return {"ok": True}


@router.post("/api/v1/tests/{test_id}/enable", response_model=dict)
async def api_enable_test(
    request: fastapi.Request, test_id: str,
    auth: Annotated[registry_auth.RequestAuth, fastapi.Depends(registry_auth.require_tenant_auth)],
) -> Record:
    """Clear disablement through the existing tenant-scoped database operation.

    Returns:
        The existing success envelope.

    Raises:
        HTTPException: No test was updated.
    """
    context = RegistryContext(cast("fastapi.FastAPI", request.app))
    updated = await asyncio.to_thread(
        dbm.set_test_disabled, context.settings, tenant_id=auth.tenant_id, test_id=test_id,
        disabled=False, reason=None, until_ts=None,
    )
    if not updated:
        raise fastapi.HTTPException(status_code=404, detail="not_found")
    return {"ok": True}


@router.post("/api/v1/tests/{test_id}/run", response_model=dict)
async def api_run_now(
    request: fastapi.Request, test_id: str,
    auth: Annotated[registry_auth.RequestAuth, fastapi.Depends(registry_auth.require_tenant_auth)],
) -> Record:
    """Request the original tenant-scoped run scheduling operation.

    Returns:
        The existing success envelope.

    Raises:
        HTTPException: No matching test was scheduled.
    """
    context = RegistryContext(cast("fastapi.FastAPI", request.app))
    updated = await asyncio.to_thread(
        dbm.trigger_run_now, context.settings, tenant_id=auth.tenant_id, test_id=test_id,
    )
    if not updated:
        raise fastapi.HTTPException(status_code=404, detail="not_found")
    return {"ok": True}
