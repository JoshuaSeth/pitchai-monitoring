# Copyright (c) 2026 PitchAI. All rights reserved.
"""FastAPI authentication dependencies for registry actors."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, cast

from fastapi import Depends, HTTPException, Request

from e2e_registry.db import AuthedTenant, get_api_key_by_hash
from e2e_registry.settings import RegistrySettings

if TYPE_CHECKING:
    from fastapi import FastAPI

_AUTHORIZATION_PART_COUNT = 2
_RUNTIME_ANNOTATIONS = (Request, AuthedTenant)


def hash_token(token: str) -> str:
    """Return a SHA-256 digest for a non-empty bearer token."""
    s = (token or "").strip()
    if not s:
        return ""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _auth_header_token(req: Request) -> str:
    raw = req.headers.get("authorization") or ""
    if not raw:
        return ""
    parts = raw.split(None, 1)
    if len(parts) != _AUTHORIZATION_PART_COUNT:
        return ""
    scheme, rest = parts[0].strip().lower(), parts[1].strip()
    if scheme != "bearer":
        return ""
    return rest


@dataclass(frozen=True)
class RequestAuth:
    """Tenant identity attached to an authenticated request."""

    tenant_id: str
    api_key_id: str


def get_settings(req: Request) -> RegistrySettings:
    """Return the registry settings installed during application startup.

    Raises:
        TypeError: If startup did not install typed registry settings.
    """
    application = cast("FastAPI", req.app)
    settings: object = getattr(application.state, "settings", None)
    if not isinstance(settings, RegistrySettings):
        msg = "Registry settings not configured"
        raise TypeError(msg)
    return settings


def require_tenant_auth(
    req: Request,
    settings: Annotated[RegistrySettings, Depends(get_settings)],
) -> RequestAuth:
    """Authenticate a tenant bearer token.

    Returns:
        The authenticated tenant and API-key identity.

    Raises:
        HTTPException: If the bearer token is missing or invalid.
    """
    token = _auth_header_token(req)
    if not token:
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    token_hash = hash_token(token)
    authed: AuthedTenant | None = get_api_key_by_hash(settings, token_hash=token_hash)
    if authed is None:
        raise HTTPException(status_code=403, detail="invalid_token")
    return RequestAuth(tenant_id=authed.tenant_id, api_key_id=authed.api_key_id)


def require_admin(
    req: Request,
    settings: Annotated[RegistrySettings, Depends(get_settings)],
) -> None:
    """Require the configured administrator bearer token.

    Raises:
        HTTPException: If administrator authentication is unavailable or fails.
    """
    token = _auth_header_token(req)
    if not token:
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="admin_token_not_configured")
    if not hmac.compare_digest(token.strip(), settings.admin_token.strip()):
        raise HTTPException(status_code=403, detail="invalid_admin_token")


def require_runner(
    req: Request,
    settings: Annotated[RegistrySettings, Depends(get_settings)],
) -> None:
    """Require the configured runner bearer token.

    Raises:
        HTTPException: If runner authentication is unavailable or fails.
    """
    token = _auth_header_token(req)
    if not token:
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    if not settings.runner_token:
        raise HTTPException(status_code=503, detail="runner_token_not_configured")
    if not hmac.compare_digest(token.strip(), settings.runner_token.strip()):
        raise HTTPException(status_code=403, detail="invalid_runner_token")
