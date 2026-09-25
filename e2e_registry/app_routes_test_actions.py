# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tenant test actions and health-summary authorization routes."""

import asyncio
import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from e2e_registry import db as dbm
from e2e_registry.app_context import context_from_request
from e2e_registry.app_policy import parse_until
from e2e_registry.auth import RequestAuth, require_tenant_auth
from e2e_registry.models import JsonObject, JsonValue
from e2e_registry.schema import DisableTestRequest

router = APIRouter()
_RUNTIME_ANNOTATIONS = (Request, RequestAuth, JsonObject, JsonValue, DisableTestRequest)


@router.post("/api/v1/tests/{test_id}/disable")
async def _api_disable_test(
    request: Request,
    test_id: str,
    auth: Annotated[RequestAuth, Depends(require_tenant_auth)],
    body: DisableTestRequest | None = None,
) -> JsonObject:
    if body is None:
        raise HTTPException(status_code=400, detail="missing_body")
    context = context_from_request(request)
    try:
        until_ts = parse_until(body.until)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid_until: {exc}") from exc
    updated = await asyncio.to_thread(
        dbm.set_test_disabled,
        context.settings,
        dbm.TestDisableChange(
            tenant_id=auth.tenant_id,
            test_id=test_id,
            disabled=True,
            reason=body.reason,
            until_ts=until_ts,
        ),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="not_found")
    return {"ok": True}


@router.post("/api/v1/tests/{test_id}/enable")
async def _api_enable_test(
    request: Request,
    test_id: str,
    auth: Annotated[RequestAuth, Depends(require_tenant_auth)],
) -> JsonObject:
    context = context_from_request(request)
    updated = await asyncio.to_thread(
        dbm.set_test_disabled,
        context.settings,
        dbm.TestDisableChange(
            tenant_id=auth.tenant_id,
            test_id=test_id,
            disabled=False,
            reason=None,
            until_ts=None,
        ),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="not_found")
    return {"ok": True}


@router.post("/api/v1/tests/{test_id}/run")
async def _api_run_now(
    request: Request,
    test_id: str,
    auth: Annotated[RequestAuth, Depends(require_tenant_auth)],
) -> JsonObject:
    context = context_from_request(request)
    updated = await asyncio.to_thread(
        dbm.trigger_run_now,
        context.settings,
        tenant_id=auth.tenant_id,
        test_id=test_id,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="not_found")
    return {"ok": True}


@router.get("/api/v1/status/summary")
async def _api_status_summary(request: Request) -> JsonObject:
    """Return global operator health or a tenant-filtered summary.

    Raises:
        HTTPException: If none of the supported authorization modes succeeds.
    """
    context = context_from_request(request)
    authorization = (request.headers.get("authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        provided = authorization.split(None, 1)[1].strip()
        if context.settings.admin_token and hmac.compare_digest(provided, context.settings.admin_token.strip()):
            return await asyncio.to_thread(dbm.status_summary, context.settings)
        if context.settings.monitor_token and hmac.compare_digest(provided, context.settings.monitor_token.strip()):
            return await asyncio.to_thread(dbm.status_summary, context.settings)
    try:
        tenant_auth = require_tenant_auth(request, context.settings)
    except HTTPException as exc:
        raise HTTPException(status_code=401, detail="unauthorized") from exc
    summary = await asyncio.to_thread(dbm.status_summary, context.settings)
    raw_tests = summary.get("tests")
    tests = raw_tests if isinstance(raw_tests, list) else []
    tenant_tests: list[JsonValue] = []
    failing_tests: list[JsonValue] = []
    for test in tests:
        if not isinstance(test, dict):
            continue
        if str(test.get("tenant_id") or "") != tenant_auth.tenant_id:
            continue
        tenant_tests.append(test)
        if test.get("effective_ok") not in {1, "1"}:
            failing_tests.append(test)
    return {
        "ok": True,
        "total_tests": len(tenant_tests),
        "failing_tests": len(failing_tests),
        "tests": tenant_tests,
    }


ROUTE_HANDLERS = (_api_disable_test, _api_enable_test, _api_run_now, _api_status_summary)
