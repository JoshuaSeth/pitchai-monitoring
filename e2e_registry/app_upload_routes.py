# Copyright (c) 2026 PitchAI. All rights reserved.
"""Single-file test API upload with existing admission and persistence behavior."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Annotated, cast

import fastapi

from e2e_registry.app_source_files import (
    SourceLocation,
    code_filename,
    extension_error,
    parse_upload_definition,
    sha256_hex,
)

from . import auth as registry_auth
from . import db as dbm
from .app_context import RegistryContext
from .app_host_policy import RegistryHostPolicy
from .app_inputs import normalize_test_kind
from .app_upload_values import ApiUploadForm, UploadedTest
from .stepflow import StepFlowValidationError

if TYPE_CHECKING:
    from .dashboard_records import Record

router = fastapi.APIRouter()


@router.post("/api/v1/tests/upload", response_model=dict)
async def api_upload_test(
    req: fastapi.Request,
    auth: Annotated[registry_auth.RequestAuth, fastapi.Depends(registry_auth.require_tenant_auth)],
    file: Annotated[fastapi.UploadFile, fastapi.File(...)],
    fields: Annotated[ApiUploadForm, fastapi.Depends(ApiUploadForm)],
) -> Record:
    """Upload a single-file E2E test using its original kind-specific validation.

    Returns:
        The success envelope and inserted test.

    Raises:
        HTTPException: Kind, file size, URL, definition, extension or path admission fails.
    """
    context = RegistryContext(cast("fastapi.FastAPI", req.app))
    settings = context.settings
    kind_value = normalize_test_kind(fields.kind)
    if not kind_value:
        raise fastapi.HTTPException(status_code=400, detail="invalid_kind")
    raw = await file.read()
    if int(settings.max_upload_bytes) > 0 and len(raw) > int(settings.max_upload_bytes):
        raise fastapi.HTTPException(status_code=413, detail="file_too_large")
    base = RegistryHostPolicy(context).validate_base_url(fields.base_url)
    source = UploadedTest(fields.name)
    if kind_value == "stepflow":
        try:
            source.definition = parse_upload_definition(raw, file.content_type)
        except StepFlowValidationError as exc:
            raise fastapi.HTTPException(status_code=400, detail=str(exc)) from exc
        source.name = (fields.name or "").strip() or str(source.definition.get("name") or "test")
    else:
        source.source_filename = code_filename(kind_value, file.filename)
        if error := extension_error(kind_value, source.source_filename):
            raise fastapi.HTTPException(status_code=400, detail=error)
        source.name = (fields.name or "").strip() or source.source_filename
        source.test_id = str(uuid.uuid4())
        location = SourceLocation.for_test(settings.tests_dir, auth.tenant_id, source.test_id, source.source_filename)
        if not location.contained:
            raise fastapi.HTTPException(status_code=400, detail="invalid_upload_path")
        location.write(raw)
        source.source_relpath = str(location.relative)
        source.source_sha = sha256_hex(raw)
    created = cast("Record", await asyncio.to_thread(
        dbm.insert_test, context.settings, tenant_id=auth.tenant_id, name=source.name, base_url=base,
        test_id=source.test_id, test_kind=kind_value, definition=source.definition,
        source_relpath=source.source_relpath, source_filename=source.source_filename, source_sha256=source.source_sha,
        source_content_type=file.content_type, interval_seconds=int(fields.interval_seconds),
        timeout_seconds=int(fields.timeout_seconds), jitter_seconds=int(fields.jitter_seconds),
        down_after_failures=int(fields.down_after_failures), up_after_successes=int(fields.up_after_successes),
        notify_on_recovery=str(fields.notify_on_recovery or "").strip().lower() in {"1", "true", "yes", "y", "on"},
        dispatch_on_failure=str(fields.dispatch_on_failure or "").strip().lower() in {"1", "true", "yes", "y", "on"},
    ))
    return {"ok": True, "test": created}
