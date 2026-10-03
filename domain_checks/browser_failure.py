# Copyright (c) 2026 PitchAI. All rights reserved.
"""Ordinary browser errors and the existing delayed disconnect classification."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from .browser_errors import is_browser_infra_error

if TYPE_CHECKING:
    from types import TracebackType

    from playwright.async_api import Browser

    from .event_bus_delivery import JsonObject


@dataclass
class BrowserFailure:
    """Capture an ordinary failure without consuming cancellation or fatal signals."""

    error: Exception | None = None

    def __enter__(self) -> Self:
        """Return this initially empty failure boundary."""
        return self

    def __exit__(self, _kind: type[BaseException] | None, error: BaseException | None,
                 _trace: TracebackType | None) -> bool:
        """Return true for only the original Exception catch scope."""
        if not isinstance(error, Exception):
            return False
        self.error = error
        return True


async def failure_details(browser: Browser, error: Exception, prefix: str, started: float) -> JsonObject:
    """Classify connection failure, including the original 50ms disconnect recheck.

    Returns:
        The exact failure-detail fields with timing sampled after classification.
    """
    connected = None
    with suppress(Exception):
        connected = browser.is_connected()
    infrastructure = is_browser_infra_error(error) or (connected is False)
    if not infrastructure:
        message = str(error).lower()
        if "net::err_aborted" in message or "frame was detached" in message:
            connected_later = connected
            with suppress(Exception):
                await asyncio.sleep(0.05)
                connected_later = browser.is_connected()
            if connected_later is False:
                connected = connected_later
                infrastructure = True
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "error": f"{prefix}: {type(error).__name__}: {error}", "browser_connected": connected,
        "browser_infra_error": infrastructure, "browser_elapsed_ms": round(elapsed_ms, 3),
    }
