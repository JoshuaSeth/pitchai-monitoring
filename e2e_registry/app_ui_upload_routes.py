# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tenant upload-page authentication, form errors and test creation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Annotated, cast

import fastapi
from fastapi.responses import HTMLResponse, RedirectResponse

from e2e_registry.app_source_files import UiUploadFailure, parse_upload_definition

from . import db as dbm
from .app_access import RegistryAccess
from .app_context import RegistryContext
from .app_host_policy import RegistryHostPolicy
from .app_inputs import normalize_test_kind
from .app_upload_page import UploadPage
from .app_upload_values import UploadedTest, UploadForm
from .stepflow import StepFlowValidationError

if TYPE_CHECKING:
    from .dashboard_records import Record

router = fastapi.APIRouter()


@router.get("/ui/upload", response_class=HTMLResponse, response_model=None)
async def ui_upload(req: fastapi.Request) -> HTMLResponse | RedirectResponse:
    """Show the upload form only after the original tenant-cookie lookup.

    Returns:
        The form or the login redirect.
    """
    context = RegistryContext(cast("fastapi.FastAPI", req.app))
    if await RegistryAccess(context).ui_get_auth(req) is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    return UploadPage(context, req).render()


@router.post("/ui/upload", response_class=HTMLResponse, response_model=None)
async def ui_upload_post(
    req: fastapi.Request, file: Annotated[fastapi.UploadFile, fastapi.File(...)],
    fields: Annotated[UploadForm, fastapi.Depends(UploadForm)],
) -> HTMLResponse | RedirectResponse:
    """Retain upload form validation, file persistence and database error rendering.

    Returns:
        The original form error/success response or unauthenticated login redirect.
    """
    page = UploadPage(RegistryContext(cast("fastapi.FastAPI", req.app)), req)
    authed = await RegistryAccess(page.context).ui_get_auth(req)
    if authed is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    raw = await file.read()
    settings = page.context.settings
    kind = normalize_test_kind(fields.kind)
    error = "invalid_kind" if not kind else None
    if not error and int(settings.max_upload_bytes) > 0 and len(raw) > int(settings.max_upload_bytes):
        error = "file_too_large"
    if error:
        return page.render(error=error)
    try:
        base = RegistryHostPolicy(page.context).validate_base_url(fields.base_url)
    except fastapi.HTTPException as exc:
        return page.render(error=str(exc.detail))
    source = UploadedTest((fields.name or "").strip(), content_type=file.content_type)
    if kind == "stepflow":
        try:
            source.definition = parse_upload_definition(raw, file.content_type)
        except StepFlowValidationError as exc:
            return page.render(error=str(exc))
        source.name = source.name or str(source.definition.get("name") or "test")
    else:
        source.source_filename = file.filename
        error = page.prepare_code(source, raw, tenant_id=authed.tenant_id, kind=kind)
        if error:
            return page.render(error=error)
    created: Record = {}
    with UiUploadFailure() as insertion:
        created = cast("Record", await asyncio.to_thread(
            dbm.insert_test, page.context.settings, tenant_id=authed.tenant_id, name=source.name, base_url=base,
            test_kind=kind, definition=source.definition, source_relpath=source.source_relpath,
            source_filename=source.source_filename, source_sha256=source.source_sha,
            source_content_type=source.content_type, test_id=source.test_id,
            interval_seconds=int(fields.interval_seconds), timeout_seconds=45, jitter_seconds=30,
            down_after_failures=2, up_after_successes=2, notify_on_recovery=False, dispatch_on_failure=False,
        ))
    return (page.render(error=f"db_error: {insertion.error}") if insertion.error is not None
            else page.render(message=f"Created test {created.get('id')}"))
