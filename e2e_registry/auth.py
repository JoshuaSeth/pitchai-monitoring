# Copyright (c) 2026 PitchAI. All rights reserved.
"""Registry bearer admission with the original dependency and failure order."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import fastapi

from .db import get_api_key_by_hash
from .settings import RegistrySettings

if TYPE_CHECKING:
    from .db import AuthedTenant

_HEADER_PARTS = 2


def hash_token(token: str) -> str:
    """Return the original hash of a stripped token, or an empty hash for blank input."""
    stripped = (token or "").strip()
    if not stripped:
        return ""
    return hashlib.sha256(stripped.encode("utf-8")).hexdigest()


def _auth_header_token(req: fastapi.Request) -> str:
    raw = req.headers.get("authorization") or ""
    if not raw:
        return ""
    parts = raw.split(None, 1)
    if len(parts) != _HEADER_PARTS:
        return ""
    scheme, rest = parts[0].strip().lower(), parts[1].strip()
    if scheme != "bearer":
        return ""
    return rest


@dataclass(frozen=True)
class RequestAuth:
    """Tenant/key identity returned by the original token lookup."""

    tenant_id: str
    api_key_id: str


def get_settings(req: fastapi.Request) -> RegistrySettings:
    """Validate the current application settings at each dependency resolution.

    Returns:
        The same settings object installed on the request's application.

    Raises:
        RuntimeError: Application state has missing or invalid settings.
    """
    application = cast("fastapi.FastAPI", req.app)
    settings = cast("RegistrySettings | None", getattr(application.state, "settings", None))
    if isinstance(settings, RegistrySettings):
        return settings
    # Keep the existing configuration failure class, including invalid state.
    message = "Registry settings not configured"
    raise RuntimeError(message)


# FastAPI replaces this default with get_settings' validated result. Keep the
# actual Depends default for existing request resolution and direct-call behavior.
_SETTINGS_DEPENDENCY = cast("RegistrySettings", fastapi.Depends(get_settings))


def _required_token(req: fastapi.Request) -> str:
    token = _auth_header_token(req)
    if not token:
        raise fastapi.HTTPException(status_code=401, detail="missing_bearer_token")
    return token


def require_tenant_auth(
    req: fastapi.Request, settings: RegistrySettings = _SETTINGS_DEPENDENCY,
) -> RequestAuth:
    """Keep bearer validation before the original tenant/key lookup.

    Returns:
        The tenant and API-key identifiers from the same database result.

    Raises:
        fastapi.HTTPException: A missing or unrecognized bearer fails admission.
    """
    token = _required_token(req)
    token_hash = hash_token(token)
    authed: AuthedTenant | None = get_api_key_by_hash(settings, token_hash=token_hash)
    if authed is None:
        raise fastapi.HTTPException(status_code=403, detail="invalid_token")
    return RequestAuth(tenant_id=authed.tenant_id, api_key_id=authed.api_key_id)


def _validate_role_token(token: str, configured: str, role: str) -> None:
    if not configured:
        raise fastapi.HTTPException(status_code=503, detail=f"{role}_token_not_configured")
    if not hmac.compare_digest(token.strip(), configured.strip()):
        raise fastapi.HTTPException(status_code=403, detail=f"invalid_{role}_token")


def require_admin(req: fastapi.Request, settings: RegistrySettings = _SETTINGS_DEPENDENCY) -> None:
    """Keep missing-bearer, unconfigured-token and constant-time comparison order."""
    token = _required_token(req)
    _validate_role_token(token, settings.admin_token, "admin")


def require_runner(req: fastapi.Request, settings: RegistrySettings = _SETTINGS_DEPENDENCY) -> None:
    """Keep runner admission independent of the admin and tenant credentials."""
    token = _required_token(req)
    _validate_role_token(token, settings.runner_token, "runner")
