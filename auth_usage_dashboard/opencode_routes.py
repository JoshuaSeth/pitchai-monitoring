# Copyright (c) 2026 PitchAI. All rights reserved.
"""Protected ``/api/v1/opencode-accounts`` route for the OpenCode Go subscription list."""

from __future__ import annotations

import os
from asyncio import to_thread
from pathlib import Path
from typing import TYPE_CHECKING

from .opencode_projection import OPENCODE_ACCOUNTS_FILE, load_opencode
from .scheduling_web_runtime import json_response_factory

if TYPE_CHECKING:
    from collections.abc import Callable

    from .scheduling_web_runtime import Application, Response
    from .settings import DashboardSettings

OPENCODE_ACCOUNTS_FILE_ENVIRONMENT_VARIABLE = "AUTH_USAGE_OPENCODE_ACCOUNTS_FILE"


def opencode_accounts_file() -> Path:
    """Return the exporter snapshot path, honouring the environment override."""
    configured = os.environ.get(OPENCODE_ACCOUNTS_FILE_ENVIRONMENT_VARIABLE)
    return Path(configured) if configured else OPENCODE_ACCOUNTS_FILE


def register_opencode_route(
    application: Application,
    *,
    settings: DashboardSettings,
    identity_default: str | None,
    require_operator: Callable[[DashboardSettings, str | None], None],
) -> None:
    """Register ``GET /api/v1/opencode-accounts``."""

    async def opencode_accounts(proxy_identity: str | None = identity_default) -> Response:
        require_operator(settings, proxy_identity)
        payload = await to_thread(load_opencode, opencode_accounts_file())
        return json_response_factory(payload)

    application.add_api_route("/api/v1/opencode-accounts", opencode_accounts, methods=["GET"], response_model=None)
