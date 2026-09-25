# Copyright (c) 2026 PitchAI. All rights reserved.
"""Owned Playwright browser-session lifecycle for submitted tests."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Never

from playwright.async_api import Error as PlaywrightError

from domain_checks.common_check import chromium_launch_arguments, find_chromium_executable
from e2e_sandbox.errors import BrowserStartupError, safe_text
from e2e_sandbox.routing import filter_route

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.async_api import Browser, BrowserContext, Page, Playwright

    from e2e_sandbox.models import SandboxRequest

    type AsyncCloseable = Browser | BrowserContext | Page
    type BrowserPathResolver = Callable[[], str | None]

_MAXIMUM_ERROR_LENGTH = 2_000
LOGGER = logging.getLogger("e2e-sandbox")


@dataclass(frozen=True)
class BrowserSession:
    """Resources owned by one submitted test invocation."""

    browser: Browser
    context: BrowserContext
    page: Page
    tracing_started: bool


async def _close_resources(resources: tuple[AsyncCloseable, ...]) -> None:
    for resource in resources:
        try:
            await resource.close()
        except (OSError, RuntimeError, PlaywrightError):
            LOGGER.exception("Failed to close a submitted-test browser resource")


async def close_session(session: BrowserSession) -> None:
    """Release every resource owned by a completed browser session."""
    resources: tuple[AsyncCloseable, ...] = (session.page, session.context, session.browser)
    await _close_resources(resources)


async def _raise_startup_failure(
    *,
    error: Exception,
    resources: tuple[AsyncCloseable, ...],
    stage: str,
) -> Never:
    await _close_resources(resources)
    detail = safe_text(error, maximum_length=_MAXIMUM_ERROR_LENGTH)
    message = f"Chromium {stage} failed: {detail}"
    raise BrowserStartupError(message) from error


async def start_session(
    playwright: Playwright,
    request: SandboxRequest,
    *,
    browser_path_resolver: BrowserPathResolver = find_chromium_executable,
) -> BrowserSession:
    """Start a complete session or close every partially-created resource.

    Returns:
        A ready browser, context, and page owned by the caller.

    Raises:
        BrowserStartupError: If any browser setup stage fails.
    """
    chromium_path = browser_path_resolver()
    if chromium_path is None:
        message = "missing_chromium_executable"
        raise BrowserStartupError(message)
    try:
        browser = await playwright.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=chromium_launch_arguments(disable_dev_shm=True),
        )
    except (OSError, RuntimeError, PlaywrightError) as error:
        detail = safe_text(error, maximum_length=_MAXIMUM_ERROR_LENGTH)
        message = f"Chromium launch failed: {detail}"
        raise BrowserStartupError(message) from error

    try:
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
    except (OSError, RuntimeError, PlaywrightError) as error:
        await _raise_startup_failure(error=error, resources=(browser,), stage="context setup")

    try:
        await context.route("**/*", filter_route)
    except (OSError, RuntimeError, PlaywrightError) as error:
        await _raise_startup_failure(error=error, resources=(context, browser), stage="route setup")

    try:
        page = await context.new_page()
    except (OSError, RuntimeError, PlaywrightError) as error:
        await _raise_startup_failure(error=error, resources=(context, browser), stage="page setup")
    page.set_default_timeout(int(max(1.0, request.timeout_seconds) * 1_000.0))

    if request.trace_on_failure:
        try:
            await context.tracing.start(screenshots=True, snapshots=True, sources=False)
        except (OSError, RuntimeError, PlaywrightError) as error:
            await _raise_startup_failure(
                error=error,
                resources=(page, context, browser),
                stage="trace setup",
            )
    return BrowserSession(
        browser=browser,
        context=context,
        page=page,
        tracing_started=request.trace_on_failure,
    )
