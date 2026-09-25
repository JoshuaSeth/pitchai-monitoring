# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared Chromium lifecycle and diagnostics for E2E browser tests."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from playwright.async_api import async_playwright

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from playwright.async_api import Page


@dataclass(frozen=True)
class BrowserDiagnostics:
    """Mutable event collections populated by a browser page."""

    console_errors: list[str]
    page_errors: list[str]
    failed_requests: list[str]


@asynccontextmanager
async def chromium_page(
    chromium_path: str,
    *,
    extra_http_headers: dict[str, str] | None = None,
) -> AsyncGenerator[Page]:
    """Yield one isolated Chromium page and always close its browser.

    Yields:
        A new page in an isolated browser context.
    """
    headers = {} if extra_http_headers is None else extra_http_headers
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(extra_http_headers=headers)
        page = await context.new_page()
        try:
            yield page
        finally:
            await context.close()
            await browser.close()


def capture_browser_diagnostics(page: Page) -> BrowserDiagnostics:
    """Attach error collectors and return their live backing lists.

    Returns:
        Diagnostics populated as the page emits events.
    """
    diagnostics = BrowserDiagnostics([], [], [])
    page.on(
        "console",
        lambda message: (
            diagnostics.console_errors.append(message.text)
            if message.type == "error"
            else None
        ),
    )
    page.on("pageerror", lambda error: diagnostics.page_errors.append(str(error)))
    page.on(
        "requestfailed",
        lambda request: diagnostics.failed_requests.append(request.url),
    )
    return diagnostics
