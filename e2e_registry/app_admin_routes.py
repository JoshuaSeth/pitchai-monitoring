# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing tenant and API-key administration HTTP boundaries."""

from __future__ import annotations

import asyncio
import secrets
from typing import TYPE_CHECKING, Annotated, cast

import fastapi

from . import auth, schema
from . import db as dbm
from .app_context import RegistryContext

if TYPE_CHECKING:
    from .dashboard_records import Record

router = fastapi.APIRouter()
# FastAPI resolves these concrete request classes when registering each route.
CreateTenantRequest = schema.CreateTenantRequest
CreateApiKeyRequest = schema.CreateApiKeyRequest


@router.post("/api/v1/admin/tenants", response_model=dict)
async def api_create_tenant(
    request: fastapi.Request,
    _auth: Annotated[None, fastapi.Depends(auth.require_admin)] = None,
    req: CreateTenantRequest | None = None,
) -> Record:
    """Create a tenant after the existing administrator dependency authorizes it.

    Returns:
        The existing success envelope and database tenant record.

    Raises:
        HTTPException: The request body is absent.
    """
    if req is None:
        raise fastapi.HTTPException(status_code=400, detail="missing_body")
    context = RegistryContext(cast("fastapi.FastAPI", request.app))
    tenant = cast("Record", await asyncio.to_thread(dbm.create_tenant, context.settings, name=req.name))
    return {"ok": True, "tenant": tenant}


@router.post("/api/v1/admin/api_keys", response_model=dict)
async def api_create_api_key(
    request: fastapi.Request,
    _auth: Annotated[None, fastapi.Depends(auth.require_admin)] = None,
    req: CreateApiKeyRequest | None = None,
) -> Record:
    """Create the existing token and persist its hash after administrator admission.

    Returns:
        The existing success envelope, key record and one returned token.

    Raises:
        HTTPException: The request body is absent.
    """
    if req is None:
        raise fastapi.HTTPException(status_code=400, detail="missing_body")
    context = RegistryContext(cast("fastapi.FastAPI", request.app))
    token = secrets.token_urlsafe(32)
    token_hash = auth.hash_token(token)
    record = cast("Record", await asyncio.to_thread(
        dbm.create_api_key, context.settings, tenant_id=req.tenant_id, name=req.name, token_hash=token_hash,
    ))
    return {"ok": True, "api_key": record, "token": token}
