# Copyright (c) 2026 PitchAI. All rights reserved.
"""Browser-level proof for the production monitoring dashboard contract."""

from __future__ import annotations

import json
from functools import partial
from typing import TYPE_CHECKING, cast

import pytest
from playwright.async_api import async_playwright

from domain_checks.json_types import json_object, optional_object
from monitoring_test_support.browser_proof import (
    BrowserReceipts,
    exercise_actionable_dashboard,
    preferred_browser_executable,
    serve_monitor_data,
)
from monitoring_test_support.dashboard_server import running_dashboard_server
from monitoring_test_support.network_gateway import fetch_dashboard_contract
from monitoring_test_support.production_summary import production_dashboard_summary

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from domain_checks.json_types import JsonInput
    from monitoring_test_support.dashboard_server import DashboardServer

_HTTP_OK = 200
_HTTP_UNAUTHORIZED = 401
_HTTP_NOT_FOUND = 404


@pytest.fixture(name="dashboard_server")
def dashboard_server_fixture(tmp_path: Path) -> Iterator[DashboardServer]:
    """Yield one isolated production-shaped dashboard server."""
    with running_dashboard_server(tmp_path) as server:
        yield server


@pytest.mark.asyncio
async def test_dashboard_enforces_identity_and_exposes_v2_contract(
    dashboard_server: DashboardServer,
) -> None:
    """Keep browser SSO and machine-token monitoring routes separate."""
    receipts = await fetch_dashboard_contract(dashboard_server)
    if (
        receipts.identity.anonymous.status_code != _HTTP_UNAUTHORIZED
        or receipts.identity.wrong_tenant.status_code != _HTTP_UNAUTHORIZED
    ):
        pytest.fail("dashboard accepted an unauthenticated or non-PitchAI browser identity")
    if (
        receipts.authorized.browser_summary.status_code != _HTTP_OK
        or receipts.authorized.machine_summary.status_code != _HTTP_OK
    ):
        pytest.fail("an authorized monitoring summary route failed")
    if receipts.identity.browser_with_token.status_code != _HTTP_UNAUTHORIZED:
        pytest.fail("machine token crossed into the browser SSO route")
    if receipts.identity.login.status_code != _HTTP_NOT_FOUND:
        pytest.fail("dashboard exposed an obsolete local login route")
    if (
        receipts.authorized.stylesheet.status_code != _HTTP_OK
        or receipts.authorized.script.status_code != _HTTP_OK
    ):
        pytest.fail("dashboard assets were not served locally")
    summary = json_object(cast("JsonInput", json.loads(receipts.authorized.browser_summary.text)))
    dashboards = optional_object(summary.get("dashboards"))
    required_tabs = {"infrastructure", "reliability", "journeys", "databases"}
    if not required_tabs.issubset(dashboards):
        pytest.fail(f"monitoring v2 dashboard payload is incomplete: {sorted(dashboards)}")


@pytest.mark.asyncio
async def test_dashboard_renders_production_inventory_incidents_and_tabs(
    dashboard_server: DashboardServer,
) -> None:
    """Exercise all production domains and actionable tabs in a real browser."""
    chromium_path = preferred_browser_executable()
    if chromium_path is None:
        pytest.skip("No chromium/chrome available for Playwright")
    summary = production_dashboard_summary()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            extra_http_headers={"X-PitchAI-Email": "operator@pitchai.net"},
        )
        page = await context.new_page()
        receipts = BrowserReceipts()
        page.on("console", receipts.record_console)
        page.on("pageerror", receipts.record_page_error)
        page.on("requestfailed", receipts.record_failed_request)
        await page.route(
            "**/dashboard/api/v1/monitoring/**",
            partial(serve_monitor_data, summary),
        )
        try:
            await exercise_actionable_dashboard(page, dashboard_server.base_url, receipts)
        finally:
            await context.close()
            await browser.close()
