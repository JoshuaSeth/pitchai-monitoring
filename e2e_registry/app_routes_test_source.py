# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tenant UI and API routes for code-test source replacement."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from e2e_registry import db as dbm
from e2e_registry.app_context import context_from_request
from e2e_registry.app_routes_test_lookup import require_tenant_test
from e2e_registry.app_routes_ui_tests import test_detail_redirect
from e2e_registry.auth import RequestAuth, require_tenant_auth
from e2e_registry.models import JsonObject
from e2e_registry.source_files import (
    SourceFileError,
    definition_download_path,
    remove_replaced_source,
    source_download_path,
    store_source,
    validated_source_filename,
)

if TYPE_CHECKING:
    from e2e_registry.settings import RegistrySettings
    from e2e_registry.source_files import StoredSource

router = APIRouter()
_RUNTIME_ANNOTATIONS = (Request, UploadFile, RedirectResponse, RequestAuth, JsonObject)


def _store_uploaded_source(
    settings: RegistrySettings,
    *,
    source_identity: tuple[str, str],
    storage_identity: tuple[str, str],
    content: bytes,
) -> StoredSource:
    kind, supplied_filename = source_identity
    tenant_id, test_id = storage_identity
    filename = validated_source_filename(kind, supplied_filename)
    return store_source(
        settings,
        tenant_id=tenant_id,
        test_id=test_id,
        filename=filename,
        content=content,
    )


@router.post("/ui/tests/{test_id}/source")
async def _ui_update_test_source(
    request: Request,
    test_id: str,
    file: Annotated[UploadFile, File()],
) -> RedirectResponse:
    context = context_from_request(request)
    authenticated = await context.require_ui_auth(request)
    test = await asyncio.to_thread(
        dbm.get_test,
        context.settings,
        tenant_id=authenticated.tenant_id,
        test_id=test_id,
    )
    if test is None:
        return test_detail_redirect(test_id, "Test not found")
    kind = str(test.get("test_kind") or "stepflow").strip().lower() or "stepflow"
    if kind == "stepflow":
        return test_detail_redirect(test_id, "StepFlow tests use definition updates")
    content = await file.read()
    if context.settings.max_upload_bytes > 0 and len(content) > context.settings.max_upload_bytes:
        return test_detail_redirect(test_id, "File too large")
    try:
        stored = _store_uploaded_source(
            context.settings,
            source_identity=(kind, file.filename or ""),
            storage_identity=(authenticated.tenant_id, test_id),
            content=content,
        )
    except (OSError, SourceFileError) as exc:
        return test_detail_redirect(test_id, f"Write failed: {exc}")
    updated = await asyncio.to_thread(
        dbm.update_test_source,
        context.settings,
        dbm.TestSourceUpdate(
            tenant_id=authenticated.tenant_id,
            test_id=test_id,
            source_relpath=stored.relative_path,
            source_filename=stored.filename,
            source_sha256=stored.sha256,
            source_content_type=file.content_type,
        ),
    )
    if not updated:
        return test_detail_redirect(test_id, "Update failed")
    remove_replaced_source(
        context.settings,
        old_relative_path=str(test.get("source_relpath") or "").strip(),
        new_relative_path=stored.relative_path,
    )
    return test_detail_redirect(test_id, "Source updated")


@router.get("/api/v1/tests/{test_id}/source")
async def _api_get_test_source(
    request: Request,
    test_id: str,
    auth: Annotated[RequestAuth, Depends(require_tenant_auth)],
) -> FileResponse:
    context = context_from_request(request)
    test = await require_tenant_test(
        context,
        tenant_id=auth.tenant_id,
        test_id=test_id,
    )
    kind = str(test.get("test_kind") or "stepflow").strip().lower() or "stepflow"
    if kind == "stepflow":
        definition_json = str(test.get("definition_json") or "").strip() or "{}"
        path = definition_download_path(
            context.settings,
            tenant_id=auth.tenant_id,
            test_id=test_id,
            definition_json=definition_json,
        )
        return FileResponse(str(path), media_type="application/json")
    try:
        path = source_download_path(context.settings, test)
    except SourceFileError as exc:
        status_code = 404 if str(exc) in {"source_missing", "source_not_found"} else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return FileResponse(str(path))


@router.post("/api/v1/tests/{test_id}/source")
async def _api_update_test_source(
    request: Request,
    test_id: str,
    auth: Annotated[RequestAuth, Depends(require_tenant_auth)],
    file: Annotated[UploadFile, File()],
) -> JsonObject:
    context = context_from_request(request)
    test = await require_tenant_test(
        context,
        tenant_id=auth.tenant_id,
        test_id=test_id,
    )
    kind = str(test.get("test_kind") or "stepflow").strip().lower() or "stepflow"
    if kind == "stepflow":
        raise HTTPException(status_code=400, detail="stepflow_source_updates_use_patch_definition")
    content = await file.read()
    if context.settings.max_upload_bytes > 0 and len(content) > context.settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="file_too_large")
    try:
        stored = _store_uploaded_source(
            context.settings,
            source_identity=(kind, file.filename or ""),
            storage_identity=(auth.tenant_id, test_id),
            content=content,
        )
    except SourceFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    updated = await asyncio.to_thread(
        dbm.update_test_source,
        context.settings,
        dbm.TestSourceUpdate(
            tenant_id=auth.tenant_id,
            test_id=test_id,
            source_relpath=stored.relative_path,
            source_filename=stored.filename,
            source_sha256=stored.sha256,
            source_content_type=file.content_type,
        ),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="not_found")
    remove_replaced_source(
        context.settings,
        old_relative_path=str(test.get("source_relpath") or "").strip(),
        new_relative_path=stored.relative_path,
    )
    return {"ok": True}


ROUTE_HANDLERS = (_ui_update_test_source, _api_get_test_source, _api_update_test_source)
