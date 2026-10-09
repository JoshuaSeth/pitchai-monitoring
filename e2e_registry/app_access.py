# Copyright (c) 2026 PitchAI. All rights reserved.
"""Separate tenant-cookie, operator-identity and internal monitoring access."""

from __future__ import annotations

import asyncio
import hmac
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from fastapi import HTTPException

from . import db as dbm
from .app_inputs import normalize_pitchai_email

if TYPE_CHECKING:
    from fastapi import Request

    from .app_context import RegistryContext

TENANT_COOKIE_NAME: Final = "e2e_token_hash"


@dataclass(frozen=True)
class RegistryAccess:
    """Access checks retain their distinct credentials and error responses."""

    context: RegistryContext

    async def ui_get_auth(self, request: Request) -> dbm.AuthedTenant | None:
        """Look up a nonempty tenant-cookie hash through the existing database call.

        Returns:
            The matched tenant or None, without changing the cookie.
        """
        token_hash = (request.cookies.get(TENANT_COOKIE_NAME) or "").strip()
        if not token_hash:
            return None
        return await asyncio.to_thread(dbm.get_api_key_by_hash, self.context.settings, token_hash=token_hash)

    async def ui_require_auth(self, request: Request) -> dbm.AuthedTenant:
        """Require tenant-cookie authentication for an existing UI mutation.

        Returns:
            The authenticated tenant.

        Raises:
            HTTPException: The cookie does not identify an authenticated tenant.
        """
        authed = await self.ui_get_auth(request)
        if authed is None:
            raise HTTPException(status_code=401, detail="ui_not_authenticated")
        return authed

    def dashboard_identity(self, request: Request) -> str:
        """Require the configured internal SSO identity header.

        Returns:
            The normalized internal identity.

        Raises:
            HTTPException: The identity is absent or invalid.
        """
        settings = self.context.settings
        email = normalize_pitchai_email(request.headers.get(settings.dashboard_identity_header))
        if email is None:
            raise HTTPException(status_code=401, detail="PitchAI Entra SSO identity required")
        return email

    def require_machine_token(self, request: Request) -> None:
        """Check the existing admin then monitoring credentials in constant time.

        Raises:
            HTTPException: Neither configured credential matches the bearer token.
        """
        settings = self.context.settings
        token = (request.headers.get("authorization") or "").strip()
        if token.lower().startswith("bearer "):
            provided = token.split(None, 1)[1].strip()
            if settings.admin_token and hmac.compare_digest(provided, settings.admin_token.strip()):
                return
            if settings.monitor_token and hmac.compare_digest(provided, settings.monitor_token.strip()):
                return
        raise HTTPException(status_code=401, detail="monitoring bearer token required")

    def require_monitoring_access(self, request: Request) -> None:
        """Keep SSO dashboard routes separate from the internal machine API."""
        if request.url.path.startswith("/dashboard/api/"):
            self.dashboard_identity(request)
            return
        self.require_machine_token(request)
