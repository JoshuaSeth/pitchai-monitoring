# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tenant UI source replacement, retaining its distinct redirect/error contract."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING, Annotated, cast

import fastapi
from fastapi.responses import RedirectResponse

from e2e_registry.app_source_files import SourceLocation, UiUploadFailure, code_filename, extension_error, sha256_hex

from . import db as dbm
from .app_access import RegistryAccess
from .app_context import RegistryContext

if TYPE_CHECKING:
    from .dashboard_records import Record

router = fastapi.APIRouter()


@router.post("/ui/tests/{test_id}/source")
async def ui_update_test_source(
    req: fastapi.Request, test_id: str, file: Annotated[fastapi.UploadFile, fastapi.File(...)],
) -> RedirectResponse:
    """Replace stored code bytes using the UI's existing authentication and redirects.

    Returns:
        The test-detail redirect, including the original validation/write outcome.
    """
    context = RegistryContext(cast("fastapi.FastAPI", req.app))
    authed = await RegistryAccess(context).ui_require_auth(req)
    settings = context.settings
    test = cast("Record | None", await asyncio.to_thread(
        dbm.get_test, settings, tenant_id=authed.tenant_id, test_id=test_id,
    ))
    kind = (str(test.get("test_kind") or "stepflow").strip().lower() or "stepflow") if test else ""
    if not test or kind == "stepflow":
        message = "Test+not+found" if not test else "StepFlow+tests+use+definition+updates"
        return RedirectResponse(url=f"/ui/tests/{test_id}?msg={message}", status_code=303)
    raw = await file.read()
    if int(settings.max_upload_bytes) > 0 and len(raw) > int(settings.max_upload_bytes):
        return RedirectResponse(url=f"/ui/tests/{test_id}?msg=File+too+large", status_code=303)
    filename = code_filename(kind, file.filename)
    error = extension_error(kind, filename)
    if error:
        message = "Expected+.py+file" if error == "python_test_must_be_.py" else "Expected+.js+or+.mjs+file"
        return RedirectResponse(url=f"/ui/tests/{test_id}?msg={message}", status_code=303)
    location = SourceLocation.for_test(settings.tests_dir, authed.tenant_id, str(test_id).strip(), filename)
    if not location.contained:
        return RedirectResponse(url=f"/ui/tests/{test_id}?msg=Invalid+upload+path", status_code=303)
    with UiUploadFailure() as write:
        location.write(raw)
    if write.error is not None:
        return RedirectResponse(url=f"/ui/tests/{test_id}?msg=Write+failed:+{write.error}", status_code=303)
    with suppress(Exception):
        location.remove_previous(str(test.get("source_relpath") or "").strip())
    updated = await asyncio.to_thread(
        dbm.update_test_source, settings, tenant_id=authed.tenant_id, test_id=test_id,
        source_relpath=str(location.relative), source_filename=filename,
        source_sha256=sha256_hex(raw), source_content_type=file.content_type,
    )
    message = "Source updated" if updated else "Update failed"
    return RedirectResponse(url=f"/ui/tests/{test_id}?msg={message}", status_code=303)
