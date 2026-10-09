# Copyright (c) 2026 PitchAI. All rights reserved.
"""Native domain browser lifecycle with explicit context, navigation and product phases."""

from __future__ import annotations

import time
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from .browser_content import observe_content
from .browser_failure import BrowserFailure, failure_details

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Route

    from .common_check import DomainCheckSpec
    from .event_bus_delivery import JsonObject


async def route_filter(route: Route) -> None:
    """Abort original bulky-resource classes; continue after ordinary inspection errors."""
    with suppress(Exception):
        if route.request.resource_type in {"image", "media", "font"}:
            await route.abort()
            return
    await route.continue_()


@dataclass
class BrowserObservation:
    """Own only the context/page admitted by this single domain observation."""

    browser: Browser
    started: float
    context: BrowserContext | None = None
    page: Page | None = None

    async def run(self, spec: DomainCheckSpec, timeout_ms: int) -> tuple[bool, JsonObject]:
        """Observe existing context/navigation error boundaries and product results.

        Returns:
            The original product result or phase-specific ordinary failure sentinel.
        """
        with BrowserFailure() as context_failure:
            self.context = await self.browser.new_context(viewport={"width": 1280, "height": 720})
            self.page = await self.context.new_page()
            with suppress(Exception):
                await self.context.route("**/*", route_filter)
        if context_failure.error is not None:
            details = await failure_details(self.browser, context_failure.error, "browser_context_error", self.started)
            return False, details
        # Playwright's successful new_page contract returns a Page.
        page = cast("Page", self.page)
        response = None
        with BrowserFailure() as navigation_failure:
            response = await page.goto(spec.url, wait_until="domcontentloaded", timeout=timeout_ms)
        if navigation_failure.error is not None:
            details = await failure_details(self.browser, navigation_failure.error, "browser_goto_error", self.started)
            return False, details
        ok, details = await observe_content(spec, page, response, timeout_ms)
        elapsed_ms = (time.perf_counter() - self.started) * 1000.0
        details["browser_elapsed_ms"] = round(elapsed_ms, 3)
        return ok, details

    async def close(self) -> None:
        """Close page before context; ordinary cleanup errors do not replace the result."""
        if self.page is not None:
            with suppress(Exception):
                await self.page.close()
        if self.context is not None:
            with suppress(Exception):
                await self.context.close()


async def browser_check(spec: DomainCheckSpec, browser: Browser) -> tuple[bool, JsonObject]:
    """Run the existing browser observation without converting cancellation to recovery.

    Returns:
        Product success and content-free transport classification on ordinary errors.

    """
    started = time.perf_counter()
    timeout_ms = int(spec.browser_timeout_seconds * 1000)
    observation = BrowserObservation(browser, started)
    try:
        return await _run_observation(observation, spec, timeout_ms, started)
    finally:
        await observation.close()


async def _run_observation(
    observation: BrowserObservation, spec: DomainCheckSpec, timeout_ms: int, started: float,
) -> tuple[bool, JsonObject]:
    """Apply the outer ordinary-error boundary around one admitted observation.

    Returns:
        The original result or a content-free ordinary browser-error result.

    Raises:
        RuntimeError: An inconsistent failure boundary returns without an exception.
    """
    with BrowserFailure() as failure:
        return await observation.run(spec, timeout_ms)
    if failure.error is None:
        message = "Browser failure boundary returned without an error"
        raise RuntimeError(message)
    return False, await failure_details(observation.browser, failure.error, "browser_error", started)
