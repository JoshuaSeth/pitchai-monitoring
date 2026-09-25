# Copyright (c) 2026 PitchAI. All rights reserved.
"""Browser domain-check orchestration."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from playwright.async_api import Error as PlaywrightError

from domain_checks.common_browser_assertions import evaluate_browser_page
from domain_checks.common_browser_runtime import browser_failure_details, browser_page

if TYPE_CHECKING:
    from playwright.async_api import Browser, Page, Response

    from domain_checks.common_models import DomainCheckSpec
    from domain_checks.types import JsonObject


async def _check_isolated_page(
    spec: DomainCheckSpec,
    browser: Browser,
    *,
    started: float,
    timeout_ms: int,
) -> tuple[bool, JsonObject]:
    async with browser_page(browser) as page:
        return await _check_open_page(
            spec,
            browser,
            page,
            started=started,
            timeout_ms=timeout_ms,
        )


async def _check_open_page(
    spec: DomainCheckSpec,
    browser: Browser,
    page: Page,
    *,
    started: float,
    timeout_ms: int,
) -> tuple[bool, JsonObject]:
    try:
        response: Response | None = await page.goto(
            spec.url,
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )
    except PlaywrightError as exc:
        return False, await browser_failure_details(
            browser,
            exc,
            started=started,
            prefix="browser_goto_error",
        )
    try:
        return await evaluate_browser_page(
            spec,
            page,
            response,
            timeout_ms=timeout_ms,
            started=started,
        )
    except (PlaywrightError, ValueError, TypeError) as exc:
        return False, await browser_failure_details(
            browser,
            exc,
            started=started,
            prefix="browser_error",
        )


async def browser_check(
    spec: DomainCheckSpec,
    browser: Browser,
) -> tuple[bool, JsonObject]:
    """Navigate with Playwright and evaluate a domain's browser contract.

    Returns:
        The browser-contract result and its diagnostic details.
    """
    started = time.perf_counter()
    timeout_ms = int(spec.browser_timeout_seconds * 1000)
    try:
        return await _check_isolated_page(
            spec,
            browser,
            started=started,
            timeout_ms=timeout_ms,
        )
    except PlaywrightError as exc:
        return False, await browser_failure_details(
            browser,
            exc,
            started=started,
            prefix="browser_context_error",
        )
