# Copyright (c) 2026 PitchAI. All rights reserved.
"""Registry health, tenant-session and operator dashboard HTTP boundaries."""

from __future__ import annotations

import asyncio
from typing import Annotated, cast

import fastapi
from fastapi.responses import HTMLResponse, RedirectResponse

from . import db as dbm
from .app_access import TENANT_COOKIE_NAME, RegistryAccess
from .app_context import RegistryContext
from .auth import hash_token

router = fastapi.APIRouter()


@router.get("/ui/login", response_class=HTMLResponse)
async def ui_login(req: fastapi.Request) -> HTMLResponse:
    """Render the tenant login form.

    Returns:
        The existing template and empty error.
    """
    context = RegistryContext(cast("fastapi.FastAPI", req.app))
    return context.templates.TemplateResponse("login.html", {"request": req, "error": None})


@router.post("/ui/login", response_model=None)
async def ui_login_post(
    req: fastapi.Request, api_key: Annotated[str, fastapi.Form()] = "",
) -> HTMLResponse | RedirectResponse:
    """Authenticate the supplied key and retain the existing hash-only cookie.

    Returns:
        The form error or authenticated redirect.
    """
    context = RegistryContext(cast("fastapi.FastAPI", req.app))
    token = (api_key or "").strip()
    if not token:
        return context.templates.TemplateResponse("login.html", {"request": req, "error": "Missing API key"})
    token_hash = hash_token(token)
    authed = await asyncio.to_thread(dbm.get_api_key_by_hash, context.settings, token_hash=token_hash)
    if authed is None:
        return context.templates.TemplateResponse("login.html", {"request": req, "error": "Invalid API key"})
    response = RedirectResponse(url="/ui/tests", status_code=303)
    response.set_cookie(TENANT_COOKIE_NAME, token_hash, httponly=True, samesite="lax")
    return response


@router.get("/ui/logout")
async def ui_logout() -> RedirectResponse:
    """Clear the original tenant cookie.

    Returns:
        The login redirect and cookie deletion.
    """
    response = RedirectResponse(url="/ui/login", status_code=303)
    response.delete_cookie(TENANT_COOKIE_NAME)
    return response


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(req: fastapi.Request) -> HTMLResponse:
    """Render the monitoring view after its separate SSO identity check.

    Returns:
        The unchanged dashboard context.
    """
    context = RegistryContext(cast("fastapi.FastAPI", req.app))
    actor = RegistryAccess(context).dashboard_identity(req)
    return context.templates.TemplateResponse(
        "dashboard.html", {"request": req, "title": "Monitoring", "operator_identity": actor},
    )
