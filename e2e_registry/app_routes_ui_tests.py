# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tenant UI routes for browsing and controlling registered tests."""

import asyncio
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from e2e_registry import db as dbm
from e2e_registry.app_context import context_from_request
from e2e_registry.app_policy import parse_until
from e2e_registry.models import parse_json_object
from e2e_registry.source_files import read_source_preview

router = APIRouter()
_RUNTIME_ANNOTATIONS = (Request, Response)


def test_detail_redirect(test_id: str, message: str) -> RedirectResponse:
    """Build a safely encoded tenant UI status redirect.

    Returns:
        A redirect carrying the encoded status message.
    """
    query = urlencode({"msg": message})
    return RedirectResponse(url=f"/ui/tests/{test_id}?{query}", status_code=303)


@router.get("/ui/tests", response_class=HTMLResponse)
async def _ui_tests(request: Request) -> Response:
    context = context_from_request(request)
    authenticated = await context.ui_auth(request)
    if authenticated is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    tests = await asyncio.to_thread(
        dbm.list_tests,
        context.settings,
        tenant_id=authenticated.tenant_id,
    )
    for test in tests:
        for key in ("effective_ok", "fail_streak", "success_streak"):
            if test.get(key) is not None:
                test[key] = int(str(test[key]))
    return context.templates.TemplateResponse(
        request,
        "tests.html",
        {
            "tenant_id": authenticated.tenant_id,
            "tests": tests,
        },
    )


@router.get("/ui/tests/{test_id}", response_class=HTMLResponse)
async def _ui_test_detail(
    request: Request,
    test_id: str,
    msg: str | None = None,
) -> Response:
    context = context_from_request(request)
    authenticated = await context.ui_auth(request)
    if authenticated is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    test = await asyncio.to_thread(
        dbm.get_test,
        context.settings,
        tenant_id=authenticated.tenant_id,
        test_id=test_id,
    )
    if test is None:
        raise HTTPException(status_code=404, detail="test_not_found")
    runs = await asyncio.to_thread(
        dbm.list_runs,
        context.settings,
        tenant_id=authenticated.tenant_id,
        test_id=test_id,
        limit=50,
    )
    kind = str(test.get("test_kind") or "stepflow").strip().lower() or "stepflow"
    source_filename: str | None = None
    source_text: str | None = None
    if kind != "stepflow":
        source_filename, source_text = read_source_preview(context.settings, test)
    return context.templates.TemplateResponse(
        request,
        "test_detail.html",
        {
            "test": test,
            "runs": runs,
            "definition_json": test.get("definition_json") or "",
            "source_text": source_text,
            "source_filename": source_filename,
            "msg": msg,
        },
    )


@router.post("/ui/tests/{test_id}/run")
async def _ui_test_run_now(request: Request, test_id: str) -> RedirectResponse:
    context = context_from_request(request)
    authenticated = await context.require_ui_auth(request)
    triggered = await asyncio.to_thread(
        dbm.trigger_run_now,
        context.settings,
        tenant_id=authenticated.tenant_id,
        test_id=test_id,
    )
    message = "Run triggered" if triggered else "Failed to trigger run"
    return test_detail_redirect(test_id, message)


@router.post("/ui/tests/{test_id}/disable")
async def _ui_test_disable(
    request: Request,
    test_id: str,
    reason: Annotated[str, Form()] = "temporary disable",
    until: Annotated[str, Form()] = "",
) -> RedirectResponse:
    context = context_from_request(request)
    authenticated = await context.require_ui_auth(request)
    try:
        until_ts = parse_until(until)
    except (TypeError, ValueError):
        return test_detail_redirect(test_id, "Invalid until value")
    disabled = await asyncio.to_thread(
        dbm.set_test_disabled,
        context.settings,
        dbm.TestDisableChange(
            tenant_id=authenticated.tenant_id,
            test_id=test_id,
            disabled=True,
            reason=reason,
            until_ts=until_ts,
        ),
    )
    return test_detail_redirect(test_id, "Disabled" if disabled else "Disable failed")


@router.post("/ui/tests/{test_id}/enable")
async def _ui_test_enable(request: Request, test_id: str) -> RedirectResponse:
    context = context_from_request(request)
    authenticated = await context.require_ui_auth(request)
    enabled = await asyncio.to_thread(
        dbm.set_test_disabled,
        context.settings,
        dbm.TestDisableChange(
            tenant_id=authenticated.tenant_id,
            test_id=test_id,
            disabled=False,
            reason=None,
            until_ts=None,
        ),
    )
    return test_detail_redirect(test_id, "Enabled" if enabled else "Enable failed")


@router.get("/ui/runs/{run_id}", response_class=HTMLResponse)
async def _ui_run_detail(request: Request, run_id: str) -> Response:
    context = context_from_request(request)
    authenticated = await context.ui_auth(request)
    if authenticated is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    run = await asyncio.to_thread(
        dbm.get_run,
        context.settings,
        tenant_id=authenticated.tenant_id,
        run_id=run_id,
    )
    if run is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    artifacts = parse_json_object(
        run.get("artifacts_json"),
        label="run artifacts",
        empty_when_missing=True,
    )
    return context.templates.TemplateResponse(
        request,
        "run_detail.html",
        {"run": run, "artifacts": artifacts},
    )


ROUTE_HANDLERS = (
    _ui_tests,
    _ui_test_detail,
    _ui_test_run_now,
    _ui_test_disable,
    _ui_test_enable,
    _ui_run_detail,
)
