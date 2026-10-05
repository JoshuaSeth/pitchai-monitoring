# Copyright (c) 2026 PitchAI. All rights reserved.
"""Native asynchronous registry entry callbacks, without thread-pool dispatch."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fastapi.responses import RedirectResponse

if TYPE_CHECKING:
    from .dashboard_records import Record


class RegistryEntryRoutes:
    """Stateless ASGI route callbacks retain the original event-loop execution."""

    @staticmethod
    async def health() -> Record:
        """Observe liveness without claiming dependency health.

        Returns:
            The existing success/timestamp envelope.
        """
        return {"ok": True, "ts": time.time()}

    @staticmethod
    async def root() -> RedirectResponse:
        """Enter the monitoring dashboard.

        Returns:
            The original dashboard redirect.
        """
        return RedirectResponse(url="/dashboard", status_code=303)
