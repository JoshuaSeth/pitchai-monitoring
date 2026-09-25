# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared visible-UI actions for registry browser acceptance tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from playwright.async_api import Locator, Page


@dataclass(frozen=True)
class RegistryUiUpload:
    """Values submitted through the registry upload form."""

    name: str
    base_url: str
    interval_seconds: str
    test_path: Path


async def verify_invalid_registry_key(page: Page, *, base_url: str) -> None:
    """Require an invalid API key to remain visibly rejected.

    Raises:
        AssertionError: If the UI accepts the invalid key or omits its error.
    """
    await page.goto(f"{base_url.rstrip('/')}/ui/login")
    await page.locator("[data-testid=login-api-key]").fill("invalid-key")
    await page.locator("[data-testid=login-submit]").click()
    await page.wait_for_selector("[data-testid=login-error]")
    error_text = await page.locator("[data-testid=login-error]").inner_text()
    if "Invalid" not in error_text:
        message = f"invalid registry key did not produce an error: {error_text!r}"
        raise AssertionError(message)


async def login_to_registry_ui(page: Page, *, token: str) -> None:
    """Authenticate through the visible registry login form.

    Raises:
        AssertionError: If the authenticated test list does not become visible.
    """
    await page.locator("[data-testid=login-api-key]").fill(token)
    await page.locator("[data-testid=login-submit]").click()
    await page.wait_for_selector("[data-testid=tests-title]")
    title = await page.locator("[data-testid=tests-title]").inner_text()
    if title != "Tests":
        message = f"valid registry login did not open the tests page: {title!r}"
        raise AssertionError(message)


async def submit_registry_ui_test(
    page: Page,
    *,
    upload: RegistryUiUpload,
) -> Locator:
    """Upload one test and return its validated list link.

    Returns:
        The locator for the uploaded test link.

    Raises:
        AssertionError: If the uploaded test is absent from the tests table.
    """
    await page.locator("[data-testid=nav-upload]").click()
    await page.wait_for_selector("[data-testid=upload-title]")
    await page.locator("[data-testid=upload-name]").fill(upload.name)
    await page.locator("[data-testid=upload-base-url]").fill(upload.base_url)
    await page.locator("[data-testid=upload-interval]").fill(upload.interval_seconds)
    await page.locator("[data-testid=upload-kind]").select_option(
        "playwright_python",
    )
    await page.set_input_files("[data-testid=upload-file]", str(upload.test_path))
    await page.locator("[data-testid=upload-submit]").click()
    await page.wait_for_selector("[data-testid=upload-msg]")
    await page.locator("[data-testid=nav-tests]").click()
    await page.wait_for_selector("[data-testid=tests-table]")
    test_links = page.locator("a[data-testid=test-link]", has_text=upload.name)
    link_count = await test_links.count()
    if link_count < 1:
        message = f"uploaded registry test {upload.name!r} is absent from the table"
        raise AssertionError(message)
    return test_links


async def verify_registry_test_detail(
    page: Page,
    *,
    test_links: Locator,
    expected_name: str,
) -> None:
    """Require the uploaded test detail and its source section.

    Raises:
        AssertionError: If the detail view omits the expected name or source.
    """
    await test_links.first.click()
    await page.wait_for_selector("[data-testid=test-detail-title]")
    title = await page.locator("[data-testid=test-detail-title]").inner_text()
    if expected_name not in title:
        message = f"uploaded registry test detail has the wrong title: {title!r}"
        raise AssertionError(message)
    source_sections = await page.locator("[data-testid=source-code]").count()
    if source_sections != 1:
        message = f"uploaded registry test must show one source section: {source_sections}"
        raise AssertionError(message)
