# Copyright (c) 2026 PitchAI. All rights reserved.
"""Network resource policy for submitted Playwright tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Route

_BLOCKED_RESOURCE_TYPES = frozenset({"font", "image", "media"})


async def filter_route(route: Route) -> None:
    """Abort bandwidth-heavy resources and continue all other requests."""
    if route.request.resource_type in _BLOCKED_RESOURCE_TYPES:
        await route.abort()
        return
    await route.continue_()
