# Copyright (c) 2026 PitchAI. All rights reserved.
"""Live browser-backed synthetic and web-vitals checks."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from playwright.async_api import async_playwright

from domain_checks.common_check import find_chromium_executable
from domain_checks.metrics_synthetic import run_synthetic_transactions
from domain_checks.metrics_web_vitals import measure_web_vitals
from domain_checks.testing import verify
from tests.live_metrics_support import load_enabled_specs_and_config

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from playwright.async_api import Browser

    from domain_checks.metrics_synthetic import SyntheticTransactionResult

pytestmark = pytest.mark.live
if os.getenv("RUN_LIVE_TESTS") != "1":
    pytest.skip(
        "Set RUN_LIVE_TESTS=1 to run live metric checks",
        allow_module_level=True,
    )


@pytest.fixture(name="browser")
async def live_browser() -> AsyncGenerator[Browser]:
    """Launch Chromium for live browser checks.

    Yields:
        A live Playwright browser instance.
    """
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")

    async with async_playwright() as playwright:
        browser_instance = await playwright.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            yield browser_instance
        finally:
            await browser_instance.close()


@pytest.mark.asyncio
async def test_live_synthetic_transactions_ok(browser: Browser) -> None:
    """Verify configured live synthetic transactions succeed."""
    _config, enabled_specs = load_enabled_specs_and_config()
    specs = [spec for spec in enabled_specs if spec.synthetic_transactions]
    verify(specs, "No enabled domains have synthetic_transactions configured")

    failures: list[SyntheticTransactionResult] = []
    for spec in specs:
        results = await run_synthetic_transactions(
            domain=spec.domain,
            base_url=spec.url,
            browser=browser,
            transactions=spec.synthetic_transactions,
            timeout_seconds=45.0,
        )
        failures.extend(
            result
            for result in results
            if not result.ok and not result.browser_infra_error
        )

    verify(not failures, f"Synthetic transaction failures: {failures!r}")


@pytest.mark.asyncio
async def test_live_synthetic_transactions_failure_invalid_domain(
    browser: Browser,
) -> None:
    """Verify an invalid domain produces a synthetic transaction failure."""
    results = await run_synthetic_transactions(
        domain="no-such-name.invalid",
        base_url="https://no-such-name.invalid",
        browser=browser,
        transactions=[{"name": "goto_should_fail", "steps": [{"type": "goto"}]}],
        timeout_seconds=12.0,
    )
    verify(results)
    verify(results[0].ok is False)
    verify(results[0].browser_infra_error is False)


@pytest.mark.asyncio
async def test_live_web_vitals_ok(browser: Browser) -> None:
    """Verify live web-vitals measurement succeeds for an enabled domain."""
    _config, enabled_specs = load_enabled_specs_and_config()
    if not enabled_specs:
        pytest.fail("Expected at least one enabled domain spec")
    spec = enabled_specs[0]
    result = await measure_web_vitals(
        domain=spec.domain,
        url=spec.url,
        browser=browser,
        timeout_seconds=60.0,
        post_load_wait_ms=4500,
    )
    verify(result.ok is True, f"Web vitals failed: {result!r}")
    verify("lcp_ms" in result.metrics)
    verify("cls" in result.metrics)
    verify("inp_ms" in result.metrics)


@pytest.mark.asyncio
async def test_live_web_vitals_failure_invalid_domain(browser: Browser) -> None:
    """Verify an invalid domain produces a web-vitals failure."""
    result = await measure_web_vitals(
        domain="no-such-name.invalid",
        url="https://no-such-name.invalid",
        browser=browser,
        timeout_seconds=12.0,
        post_load_wait_ms=1000,
    )
    verify(result.ok is False)
    verify(result.browser_infra_error is False)
