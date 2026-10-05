# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tenant source downloads and replacements with the original filesystem ordering."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING, Annotated, cast

import fastapi
from fastapi.responses import FileResponse

from e2e_registry.app_source_files import (
    SourceLocation,
    code_filename,
    downloadable_source,
    extension_error,
    sha256_hex,
)

from . import auth as registry_auth
from . import db as dbm
from .app_context import RegistryContext

if TYPE_CHECKING:
    from .dashboard_records import Record

router = fastapi.APIRouter()


@router.get("/api/v1/tests/{test_id}/source", response_model=None)
async def api_get_test_source(
    request: fastapi.Request, test_id: str,
    auth: Annotated[registry_auth.RequestAuth, fastapi.Depends(registry_auth.require_tenant_auth)],
) -> FileResponse:
    """Serve the existing tenant test's source or its materialized StepFlow definition.

    Returns:
        The original file response and media type.

    Raises:
        HTTPException: The test or admitted source is missing.
    """
    context = RegistryContext(cast("fastapi.FastAPI", request.app))
    test = cast("Record | None", await asyncio.to_thread(
        dbm.get_test, context.settings, tenant_id=auth.tenant_id, test_id=test_id,
    ))
    if not test:
        raise fastapi.HTTPException(status_code=404, detail="not_found")
    kind = str(test.get("test_kind") or "stepflow").strip().lower() or "stepflow"
    path = downloadable_source(context.settings.tests_dir, auth.tenant_id, test_id, test)
    return FileResponse(str(path), media_type="application/json" if kind == "stepflow" else None)


@router.post("/api/v1/tests/{test_id}/source", response_model=dict)
async def api_update_test_source(
    request: fastapi.Request, test_id: str,
    auth: Annotated[registry_auth.RequestAuth, fastapi.Depends(registry_auth.require_tenant_auth)],
    file: Annotated[fastapi.UploadFile, fastapi.File(...)],
) -> Record:
    """Replace code bytes, attempt old-file cleanup, then update the existing database record.

    Returns:
        The original success envelope.

    Raises:
        HTTPException: The test, kind, size, extension, confinement or final update fails admission.
    """
    context = RegistryContext(cast("fastapi.FastAPI", request.app))
    settings = context.settings
    test = cast("Record | None", await asyncio.to_thread(
        dbm.get_test, settings, tenant_id=auth.tenant_id, test_id=test_id,
    ))
    if not test:
        raise fastapi.HTTPException(status_code=404, detail="not_found")
    kind = str(test.get("test_kind") or "stepflow").strip().lower() or "stepflow"
    if kind == "stepflow":
        raise fastapi.HTTPException(status_code=400, detail="stepflow_source_updates_use_patch_definition")
    raw = await file.read()
    if int(settings.max_upload_bytes) > 0 and len(raw) > int(settings.max_upload_bytes):
        raise fastapi.HTTPException(status_code=413, detail="file_too_large")
    filename = code_filename(kind, file.filename)
    if error := extension_error(kind, filename):
        raise fastapi.HTTPException(status_code=400, detail=error)
    location = SourceLocation.for_test(settings.tests_dir, auth.tenant_id, str(test_id).strip(), filename)
    if not location.contained:
        raise fastapi.HTTPException(status_code=400, detail="invalid_upload_path")
    location.write(raw)
    # The previous-file removal was best-effort; its failure never cancelled the DB update.
    with suppress(Exception):
        location.remove_previous(str(test.get("source_relpath") or "").strip())
    updated = await asyncio.to_thread(
        dbm.update_test_source, settings, tenant_id=auth.tenant_id, test_id=test_id,
        source_relpath=str(location.relative), source_filename=filename,
        source_sha256=sha256_hex(raw), source_content_type=file.content_type,
    )
    if not updated:
        raise fastapi.HTTPException(status_code=404, detail="not_found")
    return {"ok": True}
