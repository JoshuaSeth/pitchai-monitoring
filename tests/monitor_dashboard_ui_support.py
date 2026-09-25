# Copyright (c) 2026 PitchAI. All rights reserved.
"""Identity, API, and responsive rendering assertions for the dashboard."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest

from domain_checks.common_check import find_chromium_executable
from e2e_registry.models import require_float
from tests.e2e_browser_support import capture_browser_diagnostics, chromium_page
from tests.monitor_dashboard_api_assertions import verify_dashboard_api

if TYPE_CHECKING:
    from playwright.async_api import Page

    from e2e_registry.models import JsonObject
    from tests.monitor_dashboard_server_support import DashboardServer

_EXPECTED_GROUP_BUTTONS = 3
_EXPECTED_CHART_PATHS = 2


async def _verify_desktop_dashboard(page: Page) -> None:
    await page.wait_for_selector("[data-testid=dash-title]")
    identity = await page.locator("[data-testid=operator-identity]").inner_text()
    if identity != "operator@pitchai.net":
        message = f"unexpected dashboard operator identity: {identity!r}"
        raise AssertionError(message)
    await page.wait_for_selector(
        "[data-testid=dash-domains-table] tbody tr[data-domain]",
    )
    await page.wait_for_function(
        "document.querySelector('#kpi-services').textContent === '1/1'",
    )
    selected = await page.locator("[data-testid=dash-selected-domain]").inner_text()
    if selected != "a.example":
        message = f"unexpected initially selected domain: {selected!r}"
        raise AssertionError(message)
    group_count = await page.locator("[data-testid=dash-domain-groups] button").count()
    if group_count != _EXPECTED_GROUP_BUTTONS:
        message = f"dashboard must render three group buttons, got {group_count}"
        raise AssertionError(message)
    inventory_note = await page.locator("#domain-inventory-note").inner_text()
    if "2 monitored domains" not in inventory_note:
        message = f"unexpected dashboard inventory note: {inventory_note!r}"
        raise AssertionError(message)
    await page.locator("#domain-group-grid button[data-group='clients']").click()
    await page.wait_for_selector("tr[data-domain='b.example']")
    disabled_row = await page.locator("tr[data-domain='b.example']").inner_text()
    if "DISABLED" not in disabled_row:
        message = f"disabled fixture domain was not labeled disabled: {disabled_row!r}"
        raise AssertionError(message)
    await page.locator("#domain-group-grid button[data-group='core']").click()
    await page.wait_for_selector("tr[data-domain='a.example']")
    incidents = await page.locator("[data-testid=dash-incidents]").inner_text()
    expected_incidents = "No current incidents. All latest effective checks are healthy."
    if incidents != expected_incidents:
        message = f"unexpected dashboard incident summary: {incidents!r}"
        raise AssertionError(message)
    await page.wait_for_selector("[data-testid=dash-chart-domain-ok] path")
    chart_paths = await page.locator("[data-testid=dash-chart-domain-ok] path").count()
    if chart_paths != _EXPECTED_CHART_PATHS:
        message = f"dashboard domain chart must render two paths, got {chart_paths}"
        raise AssertionError(message)
    await page.wait_for_selector("[data-testid=dash-dispatch-table] .diagnostic")
    dispatch_table = await page.locator("[data-testid=dash-dispatch-table]").inner_text()
    if "Root cause" not in dispatch_table:
        message = "dashboard dispatch table must expose the root-cause diagnostic"
        raise AssertionError(message)


async def _verify_mobile_dashboard(
    page: Page,
    *,
    console_errors: list[str],
    page_errors: list[str],
    failed_requests: list[str],
) -> None:
    await page.set_viewport_size({"width": 390, "height": 844})
    await page.reload()
    await page.wait_for_selector(
        "[data-testid=dash-domains-table] tbody tr[data-domain]",
    )
    viewport = cast(
        "JsonObject",
        await page.evaluate(
            """() => ({
                innerWidth: window.innerWidth,
                documentWidth: document.documentElement.scrollWidth,
                bodyWidth: document.body.scrollWidth,
                overflowing: Array.from(document.querySelectorAll("body *"))
                    .map((element) => {
                        const rect = element.getBoundingClientRect();
                        return {tag: element.tagName, id: element.id,
                            className: String(element.className || ""),
                            left: Math.round(rect.left), right: Math.round(rect.right)};
                    })
                    .filter((item) => item.left < 0 || item.right > window.innerWidth + 1)
                    .slice(0, 12),
            })""",
        ),
    )
    diagnostic = json.dumps(viewport, indent=2)
    inner_width = require_float(
        viewport.get("innerWidth"), label="dashboard viewport width",
    )
    document_width = require_float(
        viewport.get("documentWidth"), label="dashboard document width",
    )
    if document_width > inner_width:
        message = f"dashboard document overflows mobile viewport:\n{diagnostic}"
        raise AssertionError(message)
    body_width = require_float(viewport.get("bodyWidth"), label="dashboard body width")
    if body_width > inner_width:
        message = f"dashboard body overflows mobile viewport:\n{diagnostic}"
        raise AssertionError(message)
    if viewport["overflowing"] != []:
        message = f"dashboard elements overflow mobile viewport:\n{diagnostic}"
        raise AssertionError(message)
    if console_errors:
        message = f"dashboard emitted console errors: {console_errors!r}"
        raise AssertionError(message)
    if page_errors:
        message = f"dashboard emitted page errors: {page_errors!r}"
        raise AssertionError(message)
    if failed_requests:
        message = f"dashboard issued failed requests: {failed_requests!r}"
        raise AssertionError(message)


async def verify_dashboard_identity_and_rendering(server: DashboardServer) -> None:
    """Assert Entra-only dashboard access and desktop/mobile rendering."""
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")
    await verify_dashboard_api(server)

    async with chromium_page(
        chromium_path,
        extra_http_headers={"X-PitchAI-Email": "operator@pitchai.net"},
    ) as page:
        diagnostics = capture_browser_diagnostics(page)
        await page.goto(f"{server.base_url}/dashboard")
        await _verify_desktop_dashboard(page)
        await _verify_mobile_dashboard(
            page,
            console_errors=diagnostics.console_errors,
            page_errors=diagnostics.page_errors,
            failed_requests=diagnostics.failed_requests,
        )
