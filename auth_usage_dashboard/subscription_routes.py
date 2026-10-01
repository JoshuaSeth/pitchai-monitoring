# Copyright (c) 2026 PitchAI. All rights reserved.
"""Protected route wiring for the verified subscription snapshot."""

from __future__ import annotations

import os
from asyncio import to_thread
from pathlib import Path
from typing import TYPE_CHECKING

from .scheduling_web_runtime import json_response_factory
from .subscription_accounts import SUBSCRIPTION_ACCOUNTS_FILE, read_snapshot

if TYPE_CHECKING:
    from collections.abc import Callable

    from .scheduling_web_runtime import Application, Response
    from .settings import DashboardSettings

SUBSCRIPTION_ACCOUNTS_FILE_ENVIRONMENT_VARIABLE = "AUTH_USAGE_SUBSCRIPTION_ACCOUNTS_FILE"


def register_subscription_route(
    application: Application,
    *,
    settings: DashboardSettings,
    identity_default: str | None,
    require_operator: Callable[[DashboardSettings, str | None], None],
) -> None:
    """Register the protected subscription-snapshot route."""

    async def subscription_accounts(
        proxy_identity: str | None = identity_default,
    ) -> Response:
        require_operator(settings, proxy_identity)
        configured = os.environ.get(SUBSCRIPTION_ACCOUNTS_FILE_ENVIRONMENT_VARIABLE)
        snapshot_path = Path(configured) if configured else SUBSCRIPTION_ACCOUNTS_FILE
        payload = await to_thread(read_snapshot, snapshot_path)
        return json_response_factory(payload)

    application.add_api_route(
        "/api/v1/subscription-accounts",
        subscription_accounts,
        methods=["GET"],
        response_model=None,
    )
