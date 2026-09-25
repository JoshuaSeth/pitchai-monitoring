# Copyright (c) 2026 PitchAI. All rights reserved.
"""Assert the desktop and mobile dashboard browser experience."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain_checks.testing import verify
from tests.auth_test_contract import required_value
from tests.auth_usage_ui_support import assert_no_viewport_overflow

if TYPE_CHECKING:
    from playwright.async_api import Browser, Page

EXPECTED_ACCOUNT_COUNT = 8
EXPECTED_EVENT_COUNT = 6
EXPECTED_EXPANDED_RESET_ROWS = 7
EXPECTED_FORECAST_CELL_COUNT = 3
EXPECTED_HISTORY_OPTIONS = 9
EXPECTED_RESET_ROWS = 6
EXPECTED_RUNOUT_CELL_COUNT = 3
MINIMUM_DESKTOP_CHART_WIDTH = 1300


async def exercise_dashboard(browser: Browser, base_url: str) -> None:
    """Exercise both supported dashboard viewport layouts."""
    desktop = await browser.new_page(viewport={"width": 1440, "height": 1000})
    await _assert_desktop(desktop, base_url)
    mobile = await browser.new_page(viewport={"width": 390, "height": 844})
    await _assert_mobile(mobile, base_url)


async def _assert_desktop(page: Page, base_url: str) -> None:
    """Assert dense desktop capacity, history, and reset-bank rendering."""
    _ = await page.goto(base_url, wait_until="networkidle")
    account_rows = page.locator("[data-testid=account-table] tbody tr")
    await account_rows.first.wait_for()
    verify(await account_rows.count() == EXPECTED_ACCOUNT_COUNT)
    onboarding_row = page.locator(
        "[data-testid=account-table] tbody tr",
        has_text="onboarding.bigi.net",
    )
    verify("Provider does not expose 5h" in (await onboarding_row.locator("td").nth(2).inner_text()))
    verify("No 5h reset exposed" in (await onboarding_row.locator("td").nth(3).inner_text()))
    verify("68% left" in await onboarding_row.locator("td").nth(4).inner_text())
    relay_row = page.locator(
        "[data-testid=account-table] tbody tr",
        has_text="svxjvmk78b@privaterelay.appleid.com",
    )
    relay_label = await relay_row.locator("td").first.inner_text()
    verify("routing focus" in relay_label.lower())
    decision_title = await page.locator("#decision-title").inner_text()
    verify("accounts are ready" in decision_title.lower())
    verify(await page.locator("#runout-grid .runout-cell").count() == EXPECTED_RUNOUT_CELL_COUNT)
    verify("points/hour" in await page.locator("#burn-rate").inner_text())
    forecast_cells = page.locator("#forecast-grid .forecast-cell")
    verify(await forecast_cells.count() == EXPECTED_FORECAST_CELL_COUNT)
    verify("Weekly headroom" in await forecast_cells.first.inner_text())
    verify("Unavailable" not in await page.locator("#forecast-grid").inner_text())
    verify(await page.locator("#event-list .event-item").count() == EXPECTED_EVENT_COUNT)
    verify(await page.locator("#usage-chart svg .chart-line").count() == 1)
    chart = page.locator("#usage-chart")
    chart_label = required_value(
        await chart.get_attribute("aria-label"),
        label="usage chart aria-label",
    )
    verify("hourly token usage" in chart_label)
    chart_box = required_value(
        await chart.bounding_box(),
        label="usage chart bounding box",
    )
    verify(chart_box["width"] > MINIMUM_DESKTOP_CHART_WIDTH)
    verify(await page.locator("#history-series option").count() == EXPECTED_HISTORY_OPTIONS)
    reset_rows = page.locator("#reset-bank-list .reset-bank-row")
    verify(await reset_rows.count() == EXPECTED_RESET_ROWS)
    await page.locator("#reset-bank-toggle").click()
    verify(await reset_rows.count() == EXPECTED_EXPANDED_RESET_ROWS)
    _ = await page.locator("#history-series").select_option("onboarding.bigi.net")
    selected_label = required_value(
        await chart.get_attribute("aria-label"),
        label="selected usage chart aria-label",
    )
    verify("onboarding.bigi.net" in selected_label)
    verify(await page.locator("#mobile-account-list").is_hidden())
    await assert_no_viewport_overflow(page)


async def _assert_mobile(page: Page, base_url: str) -> None:
    """Assert responsive mobile account and forecast rendering."""
    _ = await page.goto(base_url, wait_until="networkidle")
    account_cards = page.locator("#mobile-account-list .mobile-account")
    await account_cards.first.wait_for()
    verify(await account_cards.count() == EXPECTED_ACCOUNT_COUNT)
    onboarding_card = page.locator(
        "#mobile-account-list .mobile-account",
        has_text="onboarding.bigi.net",
    )
    onboarding_text = await onboarding_card.inner_text()
    verify("Provider does not expose 5h" in onboarding_text)
    verify("No 5h reset exposed" in onboarding_text)
    verify("68% left" in onboarding_text)
    relay_card = page.locator(
        "#mobile-account-list .mobile-account",
        has_text="svxjvmk78b@privaterelay.appleid.com",
    )
    verify("routing focus" in (await relay_card.inner_text()).lower())
    verify(await page.locator("#runout-grid .runout-cell").count() == EXPECTED_RUNOUT_CELL_COUNT)
    verify(await page.locator("#usage-chart svg .chart-line").count() == 1)
    verify(await page.locator(".table-shell").is_hidden())
    await assert_no_viewport_overflow(page)
