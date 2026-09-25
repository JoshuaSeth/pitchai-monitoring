# Copyright (c) 2026 PitchAI. All rights reserved.
"""PitchAI domain monitoring support for metrics web vitals."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from playwright.async_api import Error as PlaywrightError

from domain_checks.common_check import is_browser_infrastructure_error
from domain_checks.web_vitals_scripts import READ_VITALS_SCRIPT, VITALS_INIT_SCRIPT

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from playwright.async_api import Browser, BrowserContext, Page

    from domain_checks.types import JsonObject, JsonValue


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WebVitalsResult:
    """Represent WebVitalsResult."""

    domain: str
    ok: bool
    metrics: JsonObject
    error: str | None
    elapsed_ms: float | None
    browser_infra_error: bool


@dataclass(frozen=True)
class _MeasurementRequest:
    domain: str
    target_url: str
    timeout_ms: int
    post_load_wait_ms: int


async def _install_observer(page: Page) -> None:
    try:
        await page.add_init_script(VITALS_INIT_SCRIPT)
    except PlaywrightError:
        LOGGER.debug("Unable to install the web-vitals observer", exc_info=True)


async def _sample_interaction(page: Page, timeout_ms: int) -> None:
    try:
        await page.click("body", timeout=min(timeout_ms, 5000))
    except PlaywrightError:
        LOGGER.debug(
            "Unable to generate a web-vitals interaction sample",
            exc_info=True,
        )


async def _stop_observer(page: Page) -> None:
    try:
        _ = cast(
            "JsonValue",
            await page.evaluate(
                "() => window.__pitchaiVitalsStop && window.__pitchaiVitalsStop()",
            ),
        )
    except PlaywrightError:
        LOGGER.debug("Unable to stop the web-vitals observer", exc_info=True)


async def _collect_metrics(
    page: Page,
    target_url: str,
    timeout_ms: int,
    post_load_wait_ms: int,
) -> JsonObject:
    await _install_observer(page)
    _ = await page.goto(target_url, wait_until="load", timeout=timeout_ms)
    await asyncio.sleep(max(0.0, int(post_load_wait_ms) / 1000.0))
    await _sample_interaction(page, timeout_ms)
    await _stop_observer(page)
    metrics_value = cast("JsonValue", await page.evaluate(READ_VITALS_SCRIPT))
    return metrics_value if isinstance(metrics_value, dict) else {}


async def _close_page(page: Page) -> None:
    try:
        await page.close()
    except PlaywrightError:
        LOGGER.debug("Unable to close the web-vitals page", exc_info=True)


async def _close_context(context: BrowserContext) -> None:
    try:
        await context.close()
    except PlaywrightError:
        LOGGER.debug("Unable to close the web-vitals context", exc_info=True)


@asynccontextmanager
async def _measurement_page(browser: Browser) -> AsyncGenerator[Page]:
    context = await browser.new_context(viewport={"width": 1440, "height": 900})
    try:
        page = await context.new_page()
    except PlaywrightError:
        await _close_context(context)
        raise
    try:
        yield page
    finally:
        await _close_page(page)
        await _close_context(context)


async def _measure_success(
    browser: Browser,
    request: _MeasurementRequest,
    started: float,
) -> WebVitalsResult:
    async with _measurement_page(browser) as page:
        metrics = await _collect_metrics(
            page,
            request.target_url,
            request.timeout_ms,
            request.post_load_wait_ms,
        )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return WebVitalsResult(
        domain=request.domain,
        ok=True,
        metrics=metrics,
        error=None,
        elapsed_ms=round(elapsed_ms, 3),
        browser_infra_error=False,
    )


async def measure_web_vitals(
    *,
    domain: str,
    url: str,
    browser: Browser,
    timeout_seconds: float = 45.0,
    post_load_wait_ms: int = 4500,
) -> WebVitalsResult:
    """Measure browser performance signals for one domain.

    Returns:
        The collected metrics or a classified browser failure.
    """
    cleaned_domain = str(domain or "").strip().lower()
    target_url = str(url or "").strip()
    timeout_ms = int(max(1.0, float(timeout_seconds)) * 1000)
    request = _MeasurementRequest(
        domain=cleaned_domain,
        target_url=target_url,
        timeout_ms=timeout_ms,
        post_load_wait_ms=post_load_wait_ms,
    )

    started = time.perf_counter()
    try:
        return await _measure_success(
            browser,
            request,
            started,
        )
    except PlaywrightError as exc:
        browser_infra_error = is_browser_infrastructure_error(exc)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return WebVitalsResult(
            domain=cleaned_domain,
            ok=False,
            metrics={},
            error=f"{type(exc).__name__}: {exc}",
            elapsed_ms=round(elapsed_ms, 3),
            browser_infra_error=browser_infra_error,
        )
