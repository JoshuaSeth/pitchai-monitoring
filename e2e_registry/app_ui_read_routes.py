# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tenant-scoped registry test and run display routes."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

import fastapi
from fastapi.responses import HTMLResponse, RedirectResponse

from . import db as dbm
from .app_access import RegistryAccess
from .app_context import RegistryContext
from .app_ui_presentation import SourcePreview, display_artifacts, normalize_display_tests

if TYPE_CHECKING:
    from .dashboard_records import Record

router = fastapi.APIRouter()
run_router = fastapi.APIRouter()


@router.get("/ui/tests", response_class=HTMLResponse, response_model=None)
async def ui_tests(req: fastapi.Request) -> HTMLResponse | RedirectResponse:
    """List the authenticated tenant's tests with the original display normalization.

    Returns:
        The tests template or login redirect.
    """
    context = RegistryContext(cast("fastapi.FastAPI", req.app))
    authed = await RegistryAccess(context).ui_get_auth(req)
    if authed is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    tests = cast("list[Record]", await asyncio.to_thread(dbm.list_tests, context.settings, tenant_id=authed.tenant_id))
    normalize_display_tests(tests)
    return context.templates.TemplateResponse(
        "tests.html", {"request": req, "tenant_id": authed.tenant_id, "tests": tests},
    )


@router.get("/ui/tests/{test_id}", response_class=HTMLResponse, response_model=None)
async def ui_test_detail(req: fastapi.Request, test_id: str, msg: str | None = None) -> HTMLResponse | RedirectResponse:
    """Read the test before its runs and optional source preview.

    Returns:
        The detail template or login redirect.

    Raises:
        HTTPException: The tenant has no matching test.
    """
    context = RegistryContext(cast("fastapi.FastAPI", req.app))
    authed = await RegistryAccess(context).ui_get_auth(req)
    if authed is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    test = cast("Record | None", await asyncio.to_thread(
        dbm.get_test, context.settings, tenant_id=authed.tenant_id, test_id=test_id,
    ))
    if not test:
        raise fastapi.HTTPException(status_code=404, detail="test_not_found")
    runs = cast("list[Record]", await asyncio.to_thread(
        dbm.list_runs, context.settings, tenant_id=authed.tenant_id, test_id=test_id, limit=50,
    ))
    preview = SourcePreview()
    preview.read(context.settings.tests_dir, test)
    return context.templates.TemplateResponse("test_detail.html", {
        "request": req, "test": test, "runs": runs, "definition_json": test.get("definition_json") or "",
        "source_text": preview.text, "source_filename": preview.filename, "msg": msg,
    })


@run_router.get("/ui/runs/{run_id}", response_class=HTMLResponse, response_model=None)
async def ui_run_detail(req: fastapi.Request, run_id: str) -> HTMLResponse | RedirectResponse:
    """Read one tenant-scoped run and its existing best-effort artifact display.

    Returns:
        The run template or login redirect.

    Raises:
        HTTPException: The tenant has no matching run.
    """
    context = RegistryContext(cast("fastapi.FastAPI", req.app))
    authed = await RegistryAccess(context).ui_get_auth(req)
    if authed is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    run = cast("Record | None", await asyncio.to_thread(
        dbm.get_run, context.settings, tenant_id=authed.tenant_id, run_id=run_id,
    ))
    if not run:
        raise fastapi.HTTPException(status_code=404, detail="run_not_found")
    return context.templates.TemplateResponse(
        "run_detail.html", {"request": req, "run": run, "artifacts": display_artifacts(run.get("artifacts_json"))},
    )
