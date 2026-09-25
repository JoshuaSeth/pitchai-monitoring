# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed state and authorization services for the registry web app."""

from __future__ import annotations

import asyncio
import hmac
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

from fastapi import HTTPException

from e2e_registry import db as dbm
from e2e_registry import monitor_dashboard as md

if TYPE_CHECKING:
    from fastapi import FastAPI, Request
    from fastapi.templating import Jinja2Templates

    from e2e_registry.app_policy import BaseUrlPolicy
    from e2e_registry.settings import RegistrySettings

UI_AUTH_COOKIE = "e2e_token_hash"
_ALLOWED_IDENTITY_DOMAIN = "pitchai.net"
_MAX_EMAIL_LENGTH = 254
_MONITOR_CACHE_TTL_SECONDS = 5.0
_ASCII_VISIBLE_MINIMUM = 33
_ASCII_VISIBLE_MAXIMUM = 126


@dataclass
class MonitorCache:
    """Small in-process cache invalidated by source file modification times."""

    loaded_at_ts: float = 0.0
    state_mtime: float | None = None
    config_mtime: float | None = None
    data: md.MonitorData | None = None


@dataclass
class RegistryAppContext:
    """Dependencies shared by route modules."""

    settings: RegistrySettings
    templates: Jinja2Templates
    base_url_policy: BaseUrlPolicy
    monitor_cache: MonitorCache = field(default_factory=MonitorCache)

    async def ui_auth(self, request: Request) -> dbm.AuthedTenant | None:
        """Authenticate the UI cookie.

        Returns:
            The authenticated tenant, or ``None`` when the cookie is absent or invalid.
        """
        token_hash = (request.cookies.get(UI_AUTH_COOKIE) or "").strip()
        if not token_hash:
            return None
        return await asyncio.to_thread(
            dbm.get_api_key_by_hash,
            self.settings,
            token_hash=token_hash,
        )

    async def require_ui_auth(self, request: Request) -> dbm.AuthedTenant:
        """Require a valid tenant UI session.

        Returns:
            The authenticated tenant.

        Raises:
            HTTPException: If the UI session is not authenticated.
        """
        authenticated = await self.ui_auth(request)
        if authenticated is None:
            raise HTTPException(status_code=401, detail="ui_not_authenticated")
        return authenticated

    def dashboard_identity(self, request: Request) -> str:
        """Resolve a trusted PitchAI dashboard identity.

        Returns:
            The normalized PitchAI email address.

        Raises:
            HTTPException: If the trusted identity header is missing or invalid.
        """
        email = normalize_pitchai_email(request.headers.get(self.settings.dashboard_identity_header))
        if email is None:
            raise HTTPException(status_code=401, detail="PitchAI Entra SSO identity required")
        return email

    def require_monitoring_access(self, request: Request) -> None:
        """Require trusted dashboard identity or a configured monitoring token.

        Raises:
            HTTPException: If the request has no accepted monitoring authorization.
        """
        if request.url.path.startswith("/dashboard/api/"):
            self.dashboard_identity(request)
            return
        authorization = (request.headers.get("authorization") or "").strip()
        if authorization.lower().startswith("bearer "):
            provided = authorization.split(None, 1)[1].strip()
            if self.settings.admin_token and hmac.compare_digest(provided, self.settings.admin_token.strip()):
                return
            if self.settings.monitor_token and hmac.compare_digest(provided, self.settings.monitor_token.strip()):
                return
        raise HTTPException(status_code=401, detail="monitoring bearer token required")

    async def monitor_data(self) -> md.MonitorData:
        """Return monitor state, refreshing when TTL or input mtimes change."""
        now_ts = time.time()
        state_mtime = file_mtime(self.settings.monitor_state_path)
        config_mtime = file_mtime(self.settings.monitor_config_path)
        cache = self.monitor_cache
        cache_is_fresh = (
            cache.data is not None
            and cache.state_mtime == state_mtime
            and cache.config_mtime == config_mtime
            and now_ts - cache.loaded_at_ts < _MONITOR_CACHE_TTL_SECONDS
        )
        if cache_is_fresh:
            return cast("md.MonitorData", cache.data)
        data = await asyncio.to_thread(
            md.load_monitor_data,
            state_path=self.settings.monitor_state_path,
            config_path=self.settings.monitor_config_path,
        )
        cache.data = data
        cache.loaded_at_ts = now_ts
        cache.state_mtime = state_mtime
        cache.config_mtime = config_mtime
        return data


def normalize_pitchai_email(raw_email: str | None) -> str | None:
    """Normalize a trusted-header PitchAI identity, rejecting malformed input.

    Returns:
        The normalized email, or ``None`` when validation fails.
    """
    if raw_email is None or raw_email != raw_email.strip() or len(raw_email) > _MAX_EMAIL_LENGTH:
        return None
    email = raw_email.lower()
    local_part, separator, domain = email.rpartition("@")
    invalid_structure = email.count("@") != 1 or separator != "@" or not local_part
    if invalid_structure or domain != _ALLOWED_IDENTITY_DOMAIN:
        return None
    if any(ord(character) < _ASCII_VISIBLE_MINIMUM or ord(character) > _ASCII_VISIBLE_MAXIMUM for character in email):
        return None
    return email


def file_mtime(path: str) -> float | None:
    """Return a file mtime or ``None`` when the optional monitor input is absent."""
    if not path or not Path(path).exists():
        return None
    return float(Path(path).stat().st_mtime)


def context_from_request(request: Request) -> RegistryAppContext:
    """Resolve and validate the application state contract.

    Returns:
        The configured registry context.

    Raises:
        TypeError: If application startup did not install the typed context.
    """
    application = cast("FastAPI", request.app)
    context: object = getattr(application.state, "registry_context", None)
    if not isinstance(context, RegistryAppContext):
        message = "Registry application context is not configured"
        raise TypeError(message)
    return context
