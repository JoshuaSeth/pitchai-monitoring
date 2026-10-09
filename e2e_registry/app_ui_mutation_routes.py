# Copyright (c) 2026 PitchAI. All rights reserved.
"""Original tenant UI scheduling/disablement writes and redirect messages."""

from __future__ import annotations

import asyncio
from typing import Annotated, cast

import fastapi
from fastapi.responses import RedirectResponse

from . import db as dbm
from .app_access import RegistryAccess
from .app_context import RegistryContext
from .disablement import parse_disabled_until

router = fastapi.APIRouter()


@router.post("/ui/tests/{test_id}/run")
async def ui_test_run_now(req: fastapi.Request, test_id: str) -> RedirectResponse:
    """Keep tenant admission before scheduling.

    Returns:
        The original success/failure redirect.
    """
    context = RegistryContext(cast("fastapi.FastAPI", req.app))
    authed = await RegistryAccess(context).ui_require_auth(req)
    updated = await asyncio.to_thread(
        dbm.trigger_run_now, context.settings, tenant_id=authed.tenant_id, test_id=test_id,
    )
    message = "Run triggered" if updated else "Failed to trigger run"
    return RedirectResponse(url=f"/ui/tests/{test_id}?msg={message}", status_code=303)


@router.post("/ui/tests/{test_id}/disable")
async def ui_test_disable(
    req: fastapi.Request, test_id: str,
    reason: Annotated[str, fastapi.Form()] = "temporary disable", until: Annotated[str, fastapi.Form()] = "",
) -> RedirectResponse:
    """Parse disablement only after authentication and keep the existing write arguments.

    Returns:
        The original invalid-time or mutation-result redirect.
    """
    context = RegistryContext(cast("fastapi.FastAPI", req.app))
    authed = await RegistryAccess(context).ui_require_auth(req)
    try:
        until_ts = parse_disabled_until(until)
    except ValueError:
        return RedirectResponse(url=f"/ui/tests/{test_id}?msg=Invalid+until+value", status_code=303)
    updated = await asyncio.to_thread(
        dbm.set_test_disabled, context.settings, tenant_id=authed.tenant_id, test_id=test_id,
        disabled=True, reason=reason, until_ts=until_ts,
    )
    message = "Disabled" if updated else "Disable failed"
    return RedirectResponse(url=f"/ui/tests/{test_id}?msg={message}", status_code=303)


@router.post("/ui/tests/{test_id}/enable")
async def ui_test_enable(req: fastapi.Request, test_id: str) -> RedirectResponse:
    """Clear disablement through the existing tenant-scoped database write.

    Returns:
        The original mutation-result redirect.
    """
    context = RegistryContext(cast("fastapi.FastAPI", req.app))
    authed = await RegistryAccess(context).ui_require_auth(req)
    updated = await asyncio.to_thread(
        dbm.set_test_disabled, context.settings, tenant_id=authed.tenant_id, test_id=test_id,
        disabled=False, reason=None, until_ts=None,
    )
    message = "Enabled" if updated else "Enable failed"
    return RedirectResponse(url=f"/ui/tests/{test_id}?msg={message}", status_code=303)
