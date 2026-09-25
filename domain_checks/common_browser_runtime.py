# Copyright (c) 2026 PitchAI. All rights reserved.
"""Playwright lifecycle and infrastructure handling for domain checks."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.async_api import Error as PlaywrightError

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from playwright.async_api import Browser, BrowserContext, Page, Route

    from domain_checks.types import JsonObject

LOGGER = logging.getLogger(__name__)

_BROWSER_INFRASTRUCTURE_SIGNALS = (
    "target page, context or browser has been closed",
    "browser has been closed",
    "page crashed",
    "target crashed",
    "connection closed while reading from the driver",
    "connection closed while writing to the driver",
    "pipe closed by peer",
)

_CHROMIUM_CANDIDATES = (
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)

_CHROMIUM_LAUNCH_ARGUMENTS = (
    "--no-sandbox",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-sync",
    "--metrics-recording-only",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=site-per-process",
)


def chromium_launch_arguments(*, disable_dev_shm: bool) -> list[str]:
    """Build the canonical hardened Chromium launch argument list.

    Args:
        disable_dev_shm: Whether Chromium must avoid shared-memory storage.

    Returns:
        A fresh mutable launch argument list.
    """
    arguments: list[str] = list(_CHROMIUM_LAUNCH_ARGUMENTS)
    if disable_dev_shm:
        arguments.insert(1, "--disable-dev-shm-usage")
    return arguments


def is_browser_infrastructure_error(exc: Exception) -> bool:
    """Return whether an exception identifies a browser infrastructure failure."""
    if type(exc).__name__ == "TargetClosedError":
        return True
    message = str(exc or "").lower()
    return any(signal in message for signal in _BROWSER_INFRASTRUCTURE_SIGNALS)


def _browser_connection_state(browser: Browser) -> bool | None:
    try:
        return browser.is_connected()
    except PlaywrightError:
        LOGGER.debug(
            "Unable to read Playwright browser connection state",
            exc_info=True,
        )
        return None


async def browser_failure_details(
    browser: Browser,
    exc: Exception,
    *,
    started: float,
    prefix: str,
) -> JsonObject:
    """Build stable failure details and classify browser infrastructure loss.

    Returns:
        Stable browser failure diagnostics.
    """
    connected = _browser_connection_state(browser)
    infrastructure_error = is_browser_infrastructure_error(exc) or connected is False
    message = str(exc).lower()
    navigation_race = "net::err_aborted" in message or "frame was detached" in message
    if not infrastructure_error and navigation_race:
        await asyncio.sleep(0.05)
        connected = _browser_connection_state(browser)
        infrastructure_error = connected is False
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "error": f"{prefix}: {type(exc).__name__}: {exc}",
        "browser_connected": connected,
        "browser_infra_error": infrastructure_error,
        "browser_elapsed_ms": round(elapsed_ms, 3),
    }


async def block_heavy_resource(route: Route) -> None:
    """Abort expensive visual resources while retaining functional page assets."""
    if route.request.resource_type in {"image", "media", "font"}:
        await route.abort()
        return
    await route.continue_()


async def _close_page(page: Page) -> None:
    try:
        await page.close()
    except PlaywrightError:
        LOGGER.debug("Unable to close Playwright page", exc_info=True)


async def _close_context(context: BrowserContext) -> None:
    try:
        await context.close()
    except PlaywrightError:
        LOGGER.debug("Unable to close Playwright context", exc_info=True)


async def _new_page(context: BrowserContext) -> Page:
    try:
        return await context.new_page()
    except PlaywrightError:
        await _close_context(context)
        raise


async def install_resource_filter(
    context: BrowserContext,
    *,
    failure_message: str = "Unable to install Playwright resource filter",
) -> None:
    """Install the shared resource filter without failing a browser check."""
    try:
        await context.route("**/*", block_heavy_resource)
    except PlaywrightError:
        LOGGER.debug(failure_message, exc_info=True)


@asynccontextmanager
async def browser_page(browser: Browser) -> AsyncGenerator[Page]:
    """Create and reliably close an isolated browser page.

    Yields:
        An isolated Playwright page.
    """
    context = await browser.new_context(viewport={"width": 1280, "height": 720})
    page = await _new_page(context)
    await install_resource_filter(context)
    try:
        yield page
    finally:
        await _close_page(page)
        await _close_context(context)


def find_chromium_executable() -> str | None:
    """Find an explicitly configured or installed Chromium executable.

    Returns:
        The first usable executable path, or ``None`` when none is installed.
    """
    configured_path = os.getenv("CHROMIUM_PATH")
    if configured_path and Path(configured_path).exists():
        return configured_path
    for candidate in _CHROMIUM_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None
