# Copyright (c) 2026 PitchAI. All rights reserved.
"""Core, authentication, dashboard shell, and admin routes."""

import asyncio
import secrets
import time
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from e2e_registry import db as dbm
from e2e_registry.app_context import UI_AUTH_COOKIE, context_from_request
from e2e_registry.auth import hash_token, require_admin
from e2e_registry.models import JsonObject
from e2e_registry.schema import CreateApiKeyRequest, CreateTenantRequest

router = APIRouter()
_RUNTIME_ANNOTATIONS = (Request, Response, JsonObject, CreateApiKeyRequest, CreateTenantRequest)


@router.get("/health")
async def health() -> JsonObject:
    """Report process liveness.

    Returns:
        A timestamped liveness response.
    """
    payload: JsonObject = {"ok": True, "ts": time.time()}
    return payload


@router.get("/")
async def root() -> RedirectResponse:
    """Send the public root to the monitoring dashboard.

    Returns:
        A redirect to the dashboard route.
    """
    redirect_status = 303
    return RedirectResponse(url="/dashboard", status_code=redirect_status)


@router.get("/ui/login", response_class=HTMLResponse)
async def _ui_login(request: Request) -> Response:
    context = context_from_request(request)
    return context.templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/ui/login")
async def _ui_login_post(
    request: Request,
    api_key: Annotated[str, Form()] = "",
) -> Response:
    context = context_from_request(request)
    token = (api_key or "").strip()
    if not token:
        return context.templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Missing API key"},
        )
    token_hash = hash_token(token)
    authenticated = await asyncio.to_thread(
        dbm.get_api_key_by_hash,
        context.settings,
        token_hash=token_hash,
    )
    if authenticated is None:
        return context.templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid API key"},
        )
    response = RedirectResponse(url="/ui/tests", status_code=303)
    response.set_cookie(UI_AUTH_COOKIE, token_hash, httponly=True, samesite="lax")
    return response


@router.get("/ui/logout")
async def _ui_logout() -> RedirectResponse:
    response = RedirectResponse(url="/ui/login", status_code=303)
    response.delete_cookie(UI_AUTH_COOKIE)
    return response


@router.get("/dashboard", response_class=HTMLResponse)
async def _dashboard(request: Request) -> Response:
    context = context_from_request(request)
    actor = context.dashboard_identity(request)
    return context.templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "title": "Monitoring",
            "operator_identity": actor,
        },
    )


@router.post("/api/v1/admin/tenants")
async def _api_create_tenant(
    request: Request,
    _auth: Annotated[None, Depends(require_admin)],
    body: CreateTenantRequest | None = None,
) -> JsonObject:
    if body is None:
        raise HTTPException(status_code=400, detail="missing_body")
    context = context_from_request(request)
    tenant = await asyncio.to_thread(dbm.create_tenant, context.settings, name=body.name)
    return cast("JsonObject", {"ok": True, "tenant": tenant})


@router.post("/api/v1/admin/api_keys")
async def _api_create_api_key(
    request: Request,
    _auth: Annotated[None, Depends(require_admin)],
    body: CreateApiKeyRequest | None = None,
) -> JsonObject:
    if body is None:
        raise HTTPException(status_code=400, detail="missing_body")
    context = context_from_request(request)
    token = secrets.token_urlsafe(32)
    token_hash = hash_token(token)
    record = await asyncio.to_thread(
        dbm.create_api_key,
        context.settings,
        tenant_id=body.tenant_id,
        name=body.name,
        token_hash=token_hash,
    )
    return cast("JsonObject", {"ok": True, "api_key": record, "token": token})


ROUTE_HANDLERS = (
    _ui_login,
    _ui_login_post,
    _ui_logout,
    _dashboard,
    _api_create_tenant,
    _api_create_api_key,
)
