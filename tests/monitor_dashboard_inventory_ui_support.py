# Copyright (c) 2026 PitchAI. All rights reserved.
"""Production-inventory rendering assertions for the monitoring dashboard."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, cast

import pytest

from domain_checks.common_check import find_chromium_executable
from e2e_registry.models import require_float
from tests.e2e_browser_support import capture_browser_diagnostics, chromium_page
from tests.monitor_dashboard_inventory_data import production_summary

if TYPE_CHECKING:
    from playwright.async_api import Page, Route

    from e2e_registry.models import JsonObject
    from tests.monitor_dashboard_server_support import DashboardServer

_EXPECTED_GROUP_BUTTONS = 15


async def _verify_inventory_overview(page: Page) -> None:
    await page.wait_for_function(
        "document.querySelector('#kpi-services').textContent === '57/58'",
    )
    group_count = await page.locator("[data-testid=dash-domain-groups] button").count()
    if group_count != _EXPECTED_GROUP_BUTTONS:
        message = f"production dashboard must render 15 group buttons, got {group_count}"
        raise AssertionError(message)
    inventory_note = await page.locator("#domain-inventory-note").inner_text()
    if "58 monitored domains" not in inventory_note:
        message = f"unexpected production inventory note: {inventory_note!r}"
        raise AssertionError(message)
    service_detail = await page.locator("#kpi-services-detail").inner_text()
    if "1 expected" not in service_detail:
        message = f"expected-down count missing from service detail: {service_detail!r}"
        raise AssertionError(message)


async def _verify_agentcloud_policy(page: Page) -> None:
    await page.locator("[data-testid=dash-domain-filter]").fill("AgentCloud")
    await page.wait_for_selector("tr[data-domain='agentcloud.pitchai.net']")
    agentcloud_row = await page.locator(
        "tr[data-domain='agentcloud.pitchai.net']",
    ).inner_text()
    if "DOWN" not in agentcloud_row:
        message = f"AgentCloud row must show DOWN: {agentcloud_row!r}"
        raise AssertionError(message)
    if "EXPECTED · NO ALERTS" not in agentcloud_row:
        message = f"AgentCloud row must show expected-down policy: {agentcloud_row!r}"
        raise AssertionError(message)
    await page.locator("tr[data-domain='agentcloud.pitchai.net']").click()
    selected_meta = await page.locator("#selected-domain-meta").inner_text()
    if "Dashboard only · no Telegram alerts" not in selected_meta:
        message = f"AgentCloud policy metadata is missing: {selected_meta!r}"
        raise AssertionError(message)
    incident_text = await page.locator("[data-testid=dash-incidents]").inner_text()
    if "expected / dashboard only" not in incident_text.lower():
        message = f"AgentCloud incident must be marked expected: {incident_text!r}"
        raise AssertionError(message)
    if "no Telegram alert is routed" not in incident_text:
        message = f"AgentCloud incident must explain alert routing: {incident_text!r}"
        raise AssertionError(message)


async def _verify_formatief_filter(page: Page) -> None:
    await page.locator("[data-testid=dash-domain-filter]").fill("Formatief Toetsen")
    await page.wait_for_function(
        "document.querySelectorAll('[data-testid=dash-domains-table] "
        "tr[data-domain]').length === 3",
    )
    rendered = cast(
        "list[str]",
        await page.locator(
            "[data-testid=dash-domains-table] tr[data-domain]",
        ).evaluate_all("rows => rows.map(row => row.dataset.domain)"),
    )
    expected = {
        "formatief-toetsen.pitchai.net",
        "staging.formatief-toetsen.pitchai.net",
        "dft-marketing-staging.pitchai.net",
    }
    if set(rendered) != expected:
        message = f"Formatief filter rendered unexpected domains: {rendered!r}"
        raise AssertionError(message)


async def _verify_mobile_bounds(
    page: Page,
    *,
    console_errors: list[str],
    page_errors: list[str],
    failed_requests: list[str],
) -> None:
    await page.set_viewport_size({"width": 390, "height": 844})
    viewport = cast(
        "JsonObject",
        await page.evaluate(
            """() => ({innerWidth: window.innerWidth,
                documentWidth: document.documentElement.scrollWidth,
                bodyWidth: document.body.scrollWidth})""",
        ),
    )
    inner_width = require_float(
        viewport.get("innerWidth"), label="dashboard viewport width",
    )
    document_width = require_float(
        viewport.get("documentWidth"), label="dashboard document width",
    )
    if document_width > inner_width:
        message = f"production dashboard document overflows mobile viewport: {viewport!r}"
        raise AssertionError(message)
    body_width = require_float(viewport.get("bodyWidth"), label="dashboard body width")
    if body_width > inner_width:
        message = f"production dashboard body overflows mobile viewport: {viewport!r}"
        raise AssertionError(message)
    if console_errors:
        message = f"production dashboard emitted console errors: {console_errors!r}"
        raise AssertionError(message)
    if page_errors:
        message = f"production dashboard emitted page errors: {page_errors!r}"
        raise AssertionError(message)
    if failed_requests:
        message = f"production dashboard issued failed requests: {failed_requests!r}"
        raise AssertionError(message)


async def verify_complete_production_inventory(server: DashboardServer) -> None:
    """Assert all production domains, groups, policies, and mobile bounds render."""
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")
    now = time.time()
    summary = production_summary(now)

    async with chromium_page(
        chromium_path,
        extra_http_headers={"X-PitchAI-Email": "operator@pitchai.net"},
    ) as page:
        diagnostics = capture_browser_diagnostics(page)

        async def serve_monitor_data(route: Route) -> None:
            if "/monitoring/summary" in route.request.url:
                await route.fulfill(json=summary)
                return
            await route.fulfill(
                json={
                    "ok": True,
                    "domain": "fixture",
                    "samples": [
                        {
                            "ts": now - 60,
                            "ok": True,
                            "http_ms": 100.0,
                            "browser_ms": 250.0,
                        },
                        {"ts": now, "ok": True, "http_ms": 90.0, "browser_ms": 230.0},
                    ],
                },
            )

        await page.route("**/dashboard/api/v1/monitoring/**", serve_monitor_data)
        await page.goto(f"{server.base_url}/dashboard")
        await _verify_inventory_overview(page)
        await _verify_agentcloud_policy(page)
        await _verify_formatief_filter(page)
        await _verify_mobile_bounds(
            page,
            console_errors=diagnostics.console_errors,
            page_errors=diagnostics.page_errors,
            failed_requests=diagnostics.failed_requests,
        )
