# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tenant API routes for test, run, source, and artifact reads."""

import asyncio
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from e2e_registry import db as dbm
from e2e_registry.app_context import context_from_request
from e2e_registry.app_routes_test_lookup import require_tenant_test
from e2e_registry.auth import RequestAuth, require_tenant_auth
from e2e_registry.models import JsonObject
from e2e_registry.schema import PatchTestRequest
from e2e_registry.source_files import SourceFileError, artifact_download_path
from e2e_registry.stepflow import StepFlowValidationError, validate_definition

router = APIRouter()
_RUNTIME_ANNOTATIONS = (Request, RequestAuth, JsonObject, PatchTestRequest)


@router.get("/api/v1/tests")
async def _api_list_tests(
    request: Request,
    auth: Annotated[RequestAuth, Depends(require_tenant_auth)],
) -> JsonObject:
    context = context_from_request(request)
    tests = await asyncio.to_thread(
        dbm.list_tests,
        context.settings,
        tenant_id=auth.tenant_id,
    )
    return cast("JsonObject", {"ok": True, "tests": tests})


@router.get("/api/v1/tests/{test_id}")
async def _api_get_test(
    request: Request,
    test_id: str,
    auth: Annotated[RequestAuth, Depends(require_tenant_auth)],
) -> JsonObject:
    context = context_from_request(request)
    test = await require_tenant_test(
        context,
        tenant_id=auth.tenant_id,
        test_id=test_id,
    )
    return cast("JsonObject", {"ok": True, "test": test})


@router.patch("/api/v1/tests/{test_id}")
async def _api_patch_test(
    request: Request,
    test_id: str,
    auth: Annotated[RequestAuth, Depends(require_tenant_auth)],
    body: PatchTestRequest | None = None,
) -> JsonObject:
    if body is None:
        raise HTTPException(status_code=400, detail="missing_body")
    context = context_from_request(request)
    patch = cast("JsonObject", body.model_dump(exclude_unset=True))
    raw_base_url = patch.get("base_url")
    if isinstance(raw_base_url, str):
        patch["base_url"] = context.base_url_policy.validate(raw_base_url)
    raw_definition = patch.get("definition")
    if isinstance(raw_definition, dict):
        try:
            patch["definition"] = validate_definition(raw_definition)
        except StepFlowValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    updated = await asyncio.to_thread(
        dbm.patch_test,
        context.settings,
        tenant_id=auth.tenant_id,
        test_id=test_id,
        patch=patch,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="not_found")
    test = await asyncio.to_thread(
        dbm.get_test,
        context.settings,
        tenant_id=auth.tenant_id,
        test_id=test_id,
    )
    return cast("JsonObject", {"ok": True, "test": test})


@router.get("/api/v1/tests/{test_id}/runs")
async def _api_list_runs(
    request: Request,
    test_id: str,
    auth: Annotated[RequestAuth, Depends(require_tenant_auth)],
    limit: int = 50,
) -> JsonObject:
    context = context_from_request(request)
    runs = await asyncio.to_thread(
        dbm.list_runs,
        context.settings,
        tenant_id=auth.tenant_id,
        test_id=test_id,
        limit=limit,
    )
    return cast("JsonObject", {"ok": True, "runs": runs})


@router.get("/api/v1/runs/{run_id}")
async def _api_get_run(
    request: Request,
    run_id: str,
    auth: Annotated[RequestAuth, Depends(require_tenant_auth)],
) -> JsonObject:
    context = context_from_request(request)
    run = await asyncio.to_thread(
        dbm.get_run,
        context.settings,
        tenant_id=auth.tenant_id,
        run_id=run_id,
    )
    if run is None:
        raise HTTPException(status_code=404, detail="not_found")
    return cast("JsonObject", {"ok": True, "run": run})


@router.get("/api/v1/runs/{run_id}/artifacts/{name}")
async def _api_get_artifact(
    request: Request,
    run_id: str,
    name: str,
    auth: Annotated[RequestAuth, Depends(require_tenant_auth)],
) -> FileResponse:
    context = context_from_request(request)
    run = await asyncio.to_thread(
        dbm.get_run,
        context.settings,
        tenant_id=auth.tenant_id,
        run_id=run_id,
    )
    if run is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    test_id = str(run.get("test_id") or "").strip()
    if not test_id:
        raise HTTPException(status_code=404, detail="test_not_found")
    try:
        path = artifact_download_path(
            context.settings,
            tenant_id=auth.tenant_id,
            test_id=test_id,
            run_id=run_id,
            artifact_name=name,
        )
    except SourceFileError as exc:
        status_code = 404 if str(exc) == "artifact_not_found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return FileResponse(str(path))


ROUTE_HANDLERS = (
    _api_list_tests,
    _api_get_test,
    _api_patch_test,
    _api_list_runs,
    _api_get_run,
    _api_get_artifact,
)
