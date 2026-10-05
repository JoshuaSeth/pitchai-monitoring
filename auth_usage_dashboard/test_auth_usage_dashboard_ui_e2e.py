# Copyright (c) 2026 PitchAI. All rights reserved.
"""Headless-Chromium proof that the legacy dashboard renders densely and responsively."""

from __future__ import annotations

import unittest
from dataclasses import replace
from typing import TYPE_CHECKING, final

from ._dashboard_api_test_runtime import StaticBrokerSource, dashboard_application, legacy_settings
from ._dashboard_server_test_runtime import serve_dashboard
from ._dashboard_ui_test_fixtures import ONBOARDING, RELAY, ui_accounts
from ._dashboard_ui_test_runtime import ASYNC_PLAYWRIGHT, FIND_CHROMIUM
from ._timeseries_test_fixtures import check, check_equal, isolated_root
from .timeseries_types import number_value, require_object

if TYPE_CHECKING:
    from ._dashboard_ui_test_runtime import Browser, Page
    from .timeseries_types import JsonObject

ACCOUNT_ROWS = "[data-testid=account-table] tbody tr"
MOBILE_CARDS = "#mobile-account-list .mobile-account"
ACCOUNT_COUNT = 8
MIN_DESKTOP_CHART_WIDTH = 1_300
FIVE_HOUR_HIDDEN = "Provider does not expose 5h"
NO_FIVE_HOUR_RESET = "No 5h reset exposed"
WEEKLY_LEFT = "68% left"
USAGE_CREDITS = "62,500.00 credits"
OVERFLOW_SCRIPT = """() => ({
  viewport: document.documentElement.clientWidth,
  document: document.documentElement.scrollWidth,
  body: document.body.scrollWidth
})"""


def _pixels(dimensions: JsonObject, key: str) -> float:
    """Return one measured page width.

    Returns:
        The width in CSS pixels.

    Raises:
        TypeError: If the measurement is missing or non-numeric.
    """
    value = number_value(dimensions.get(key))
    if value is None:
        message = f"page dimension {key} is not numeric"
        raise TypeError(message)
    return value


async def _check_no_viewport_overflow(page: Page) -> None:
    """Fail when the document or body scrolls horizontally beyond the viewport."""
    dimensions = require_object(await page.evaluate(OVERFLOW_SCRIPT), description="page dimensions")
    viewport = _pixels(dimensions, "viewport")
    check(_pixels(dimensions, "document") <= viewport + 1, "document overflows the viewport")
    check(_pixels(dimensions, "body") <= viewport + 1, "body overflows the viewport")


@final
class DashboardUiTest(unittest.IsolatedAsyncioTestCase):
    """Render the eight-account fleet at desktop and phone widths."""

    browser: Browser
    base_url: str

    async def asyncSetUp(self) -> None:
        """Serve the dashboard and launch headless Chromium, or skip without Chromium."""
        executable = FIND_CHROMIUM()
        if not executable:
            self.skipTest("No Chromium/Chrome executable available")
        root = self.enterContext(isolated_root())
        settings = replace(legacy_settings(root), require_proxy_auth=False)
        application = dashboard_application(settings, StaticBrokerSource(ui_accounts()))
        self.base_url = await self.enterAsyncContext(serve_dashboard(application))
        playwright = await self.enterAsyncContext(ASYNC_PLAYWRIGHT())
        self.browser = await playwright.chromium.launch(
            headless=True,
            executable_path=executable,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        self.addAsyncCleanup(self.browser.close)

    async def open_page(self, width: int, height: int) -> Page:
        """Open the dashboard in a new tab with one viewport size.

        Returns:
            The loaded dashboard tab.
        """
        page = await self.browser.new_page(viewport={"width": width, "height": height})
        response = await page.goto(self.base_url, wait_until="domcontentloaded")
        check(response is not None and response.ok, "dashboard page loads")
        return page

    async def test_desktop_dashboard_renders_dense_account_table(self) -> None:
        """Prove the desktop layout renders every account, forecast, chart, and reset."""
        desktop = await self.open_page(1440, 1000)
        rows = desktop.locator(ACCOUNT_ROWS)
        await rows.first.wait_for()
        check_equal(await rows.count(), ACCOUNT_COUNT, "desktop account rows")
        onboarding_cells = desktop.locator(ACCOUNT_ROWS, has_text=ONBOARDING).locator("td")
        check(FIVE_HOUR_HIDDEN in await onboarding_cells.nth(2).inner_text(), "five-hour window is not exposed")
        check(NO_FIVE_HOUR_RESET in await onboarding_cells.nth(3).inner_text(), "five-hour reset is not exposed")
        check(WEEKLY_LEFT in await onboarding_cells.nth(4).inner_text(), "weekly headroom")
        check(USAGE_CREDITS in await onboarding_cells.nth(6).inner_text(), "usage credit balance")
        relay_cells = desktop.locator(ACCOUNT_ROWS, has_text=RELAY).locator("td")
        check("routing focus" in (await relay_cells.first.inner_text()).lower(), "routing focus badge")
        decision = await desktop.locator("#decision-title").inner_text()
        check("accounts are ready" in decision.lower(), "decision headline")
        check_equal(await desktop.locator("#runout-grid .runout-cell").count(), 3, "run-out cells")
        check("points/hour" in await desktop.locator("#burn-rate").inner_text(), "burn rate units")
        forecast_cells = desktop.locator("#forecast-grid .forecast-cell")
        check_equal(await forecast_cells.count(), 3, "forecast cells")
        check("Weekly headroom" in await forecast_cells.first.inner_text(), "weekly forecast basis")
        check("Unavailable" not in await desktop.locator("#forecast-grid").inner_text(), "forecasts are available")
        check_equal(await desktop.locator("#event-list .event-item").count(), 6, "scheduled events")
        check_equal(await desktop.locator("#usage-chart svg .chart-line").count(), 1, "usage chart line")
        chart = desktop.locator("#usage-chart")
        check("hourly token usage" in (await chart.get_attribute("aria-label") or ""), "chart label")
        chart_box = await chart.bounding_box()
        check(chart_box is not None and chart_box["width"] > MIN_DESKTOP_CHART_WIDTH, "chart spans the page")
        check_equal(await desktop.locator("#history-series option").count(), 9, "history series options")
        reset_rows = desktop.locator("#reset-bank-list .reset-bank-row")
        check_equal(await reset_rows.count(), 6, "collapsed reset bank rows")
        await desktop.locator("#reset-bank-toggle").click()
        check_equal(await reset_rows.count(), 7, "expanded reset bank rows")
        await desktop.locator("#history-series").select_option(ONBOARDING)
        check(ONBOARDING in (await chart.get_attribute("aria-label") or ""), "chart follows the selected series")
        check(await desktop.locator("#mobile-account-list").is_hidden(), "mobile cards are hidden on desktop")
        await _check_no_viewport_overflow(desktop)

    async def test_mobile_dashboard_renders_responsive_account_cards(self) -> None:
        """Prove the phone layout swaps the table for complete account cards."""
        mobile = await self.open_page(390, 844)
        cards = mobile.locator(MOBILE_CARDS)
        await cards.first.wait_for()
        check_equal(await cards.count(), ACCOUNT_COUNT, "mobile account cards")
        onboarding_text = await mobile.locator(MOBILE_CARDS, has_text=ONBOARDING).inner_text()
        for fragment in (FIVE_HOUR_HIDDEN, NO_FIVE_HOUR_RESET, WEEKLY_LEFT, USAGE_CREDITS):
            check(fragment in onboarding_text, f"onboarding card shows {fragment!r}")
        relay_text = await mobile.locator(MOBILE_CARDS, has_text=RELAY).inner_text()
        check("routing focus" in relay_text.lower(), "routing focus badge")
        check_equal(await mobile.locator("#runout-grid .runout-cell").count(), 3, "run-out cells")
        check_equal(await mobile.locator("#usage-chart svg .chart-line").count(), 1, "usage chart line")
        check(await mobile.locator(".table-shell").is_hidden(), "account table is hidden on phones")
        await _check_no_viewport_overflow(mobile)
