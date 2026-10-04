# Copyright (c) 2026 PitchAI. All rights reserved.
"""Optional browser vitals with the original best-effort interaction boundaries."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .browser_errors import is_browser_infra_error
from .browser_failure import BrowserFailure
from .vitals_scripts import VITALS_INIT_SCRIPT, VITALS_READ_SCRIPT

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page

    from .event_bus_delivery import JsonObject, JsonValue


@dataclass(frozen=True)
class WebVitalsResult:
    """The unchanged public observation fields; metrics come from the page script."""

    domain: str
    ok: bool
    metrics: JsonObject
    error: str | None
    elapsed_ms: float | None
    browser_infra_error: bool


@dataclass(frozen=True)
class VitalsRequest:
    """Normalized arguments, converted before the original observation timer starts."""

    domain: str
    url: str
    timeout_ms: int
    post_load_wait_ms: int


@dataclass
class VitalsSession:
    """Own only the resources admitted during one observation."""

    started: float
    context: BrowserContext | None = None
    page: Page | None = None

    async def read(self, browser: Browser, request: VitalsRequest) -> JsonObject:
        """Sample the original script while retaining optional-operation tolerance.

        Returns:
            The original metrics dictionary or the prior non-dictionary fallback.
        """
        self.context = await browser.new_context(viewport={"width": 1440, "height": 900})
        self.page = await self.context.new_page()
        # Optional observers/interactions never failed the original observation.
        with suppress(Exception):
            await self.page.add_init_script(VITALS_INIT_SCRIPT)
        _ = await self.page.goto(request.url, wait_until="load", timeout=request.timeout_ms)
        await asyncio.sleep(max(0.0, int(request.post_load_wait_ms) / 1000.0))
        with suppress(Exception):
            await self.page.click("body", timeout=min(request.timeout_ms, 5000))
        with suppress(Exception):
            await self.page.evaluate("() => window.__pitchaiVitalsStop && window.__pitchaiVitalsStop()")
        # This fixed script returns JSON. Preserve its original mapping identity.
        metrics = cast("JsonValue", await self.page.evaluate(VITALS_READ_SCRIPT))
        return metrics if isinstance(metrics, dict) else {}

    async def close(self) -> None:
        """Close page before context without consuming cancellation during cleanup."""
        if self.page is not None:
            with suppress(Exception):
                await self.page.close()
        if self.context is not None:
            with suppress(Exception):
                await self.context.close()


async def _observe(session: VitalsSession, browser: Browser, request: VitalsRequest) -> WebVitalsResult:
    """Convert ordinary observation failures at the browser boundary.

    Returns:
        The exact public success/error fields with the original classification order.

    Raises:
        RuntimeError: A failure boundary returns without recording an exception.
    """
    with BrowserFailure() as failure:
        metrics = await session.read(browser, request)
        elapsed_ms = (time.perf_counter() - session.started) * 1000.0
        return WebVitalsResult(domain=request.domain, ok=True, metrics=metrics, error=None,
                               elapsed_ms=round(elapsed_ms, 3), browser_infra_error=False)
    error = failure.error
    if error is None:
        message = "Vitals failure boundary returned without an exception"
        raise RuntimeError(message)
    infrastructure = is_browser_infra_error(error)
    elapsed_ms = (time.perf_counter() - session.started) * 1000.0
    name = "TimeoutError" if isinstance(error, PlaywrightTimeoutError) else type(error).__name__
    return WebVitalsResult(domain=request.domain, ok=False, metrics={}, error=f"{name}: {error}",
                           elapsed_ms=round(elapsed_ms, 3), browser_infra_error=infrastructure)


async def measure_web_vitals(
    *,
    domain: str,
    url: str,
    browser: Browser,
    timeout_seconds: float = 45.0,
    post_load_wait_ms: int = 4500,
) -> WebVitalsResult:
    """Run one browser observation and release its page/context in original order.

    Returns:
        The original metrics or ordinary-error sentinel with measured duration.
    """
    request = VitalsRequest(str(domain or "").strip().lower(), str(url or "").strip(),
                           int(max(1.0, float(timeout_seconds)) * 1000), post_load_wait_ms)
    session = VitalsSession(time.perf_counter())
    try:
        return await _observe(session, browser, request)
    finally:
        await session.close()
