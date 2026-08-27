# Copyright (c) 2026 PitchAI. All rights reserved.
"""Browser assertions for the actionable monitoring dashboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .domain_runtime import common_runtime
from .json_types import int_value, json_object, optional_object
from .testing_runtime import pytest

if TYPE_CHECKING:
    from .browser_runtime import BrowserRequest, ConsoleMessage, Locator, Page, Route
    from .json_types import JsonInput, JsonObject

_EXPECTED_INCIDENT_COUNT = 2
_EXPECTED_TAB_COUNT = 6
_EXPECTED_HOTPATH_LANES = 13
_MOBILE_WIDTH = 390
_MOBILE_HEIGHT = 844
_STABLE_CHROME_PATHS = (
    Path("/usr/bin/google-chrome-stable"),
    Path("/usr/bin/google-chrome"),
)


def preferred_browser_executable() -> str | None:
    """Prefer stable Chrome over the host's obsolete Chromium wrapper.

    Returns:
        The first usable browser executable, or ``None`` when unavailable.
    """
    stable_browser = next((path for path in _STABLE_CHROME_PATHS if path.is_file()), None)
    if stable_browser is not None:
        return str(stable_browser)
    return common_runtime.find_chromium_executable()


@dataclass
class BrowserReceipts:
    """Collect browser-side failures without hiding asynchronous events."""

    console_errors: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    failed_requests: list[str] = field(default_factory=list)

    def record_console(self, message: ConsoleMessage) -> None:
        """Record console errors while ignoring lower-severity diagnostics."""
        if message.type == "error":
            self.console_errors.append(message.text)

    def record_page_error(self, error: Exception) -> None:
        """Record an uncaught page exception."""
        self.page_errors.append(str(error))

    def record_failed_request(self, request: BrowserRequest) -> None:
        """Record one network request that failed at the browser boundary."""
        self.failed_requests.append(request.url)

    def failure_summary(self) -> str | None:
        """Return a compact browser failure receipt when any error occurred."""
        if not (self.console_errors or self.page_errors or self.failed_requests):
            return None
        return (
            f"console={self.console_errors!r} page={self.page_errors!r} "
            f"requests={self.failed_requests!r}"
        )


async def serve_monitor_data(summary: JsonObject, route: Route) -> None:
    """Fulfil dashboard API requests from deterministic retained data."""
    if "/hotpaths/summary" in route.request.url:
        await route.fulfill(json={"hotpaths": summary, "ok": True})
        return
    if "/monitoring/summary" in route.request.url:
        await route.fulfill(json=summary)
        return
    await route.fulfill(
        json={
            "ok": True,
            "domain": "pitchai.net",
            "samples": [
                {"ts": 1_777_000_000.0, "ok": True, "http_ms": 110.0, "browser_ms": 400.0},
                {"ts": 1_777_000_060.0, "ok": False, "http_ms": 42.1, "browser_ms": None},
            ],
        },
    )


async def _require_text(locator: Locator, expected: str) -> None:
    rendered = await locator.inner_text()
    if expected.casefold() not in rendered.casefold():
        pytest.fail(f"missing rendered dashboard text {expected!r}: {rendered!r}")


def _summary_count(summary: JsonObject, section: str, key: str) -> int:
    value = int_value(optional_object(summary.get(section)).get(key))
    if value is None:
        pytest.fail(f"dashboard proof summary is missing {section}.{key}")
    return value


async def _verify_incidents(page: Page) -> None:
    incident_toggles = page.locator("[data-testid=dash-incidents] .incident__toggle")
    if await incident_toggles.count() != _EXPECTED_INCIDENT_COUNT:
        pytest.fail("domain and database incidents were not both rendered")
    await incident_toggles.first.click()
    if await incident_toggles.first.get_attribute("aria-expanded") != "false":
        pytest.fail("domain incident did not collapse")
    await incident_toggles.first.click()
    if await incident_toggles.first.get_attribute("aria-expanded") != "true":
        pytest.fail("domain incident did not expand again")
    incident = page.locator("[data-incident-id='domain_down:pitchai.net']")
    for expected in (
        "HTTP readiness",
        "Last successful sample",
        "Safe failure evidence",
        "Suggested next action",
    ):
        await _require_text(incident, expected)
    database_incident = page.locator(
        "[data-incident-id='database_dependency:billing-web:runtime-postgres']",
    )
    await database_incident.locator(".incident__toggle").click()
    for expected in (
        "Invalid Or Revoked Password",
        "Green slot · 100% traffic",
        "Open database dependencies",
    ):
        await _require_text(database_incident, expected)


async def _verify_tabs(page: Page) -> None:
    await page.locator("#tab-domains").focus()
    await page.keyboard.press("ArrowRight")
    database_panel = page.locator("[data-testid=dash-database-dependencies]")
    for expected in (
        "Billing web",
        "login/authentication",
        "PgBouncer/tunnel connectivity",
        "schema usage grant",
        "configured table permission",
        "bounded query timeout",
        "Stale Or Revoked After Last Success",
        "Telegram incident open",
    ):
        await _require_text(database_panel, expected)
    await page.locator("[data-testid=dash-database-filter]").fill("revoked")
    if await page.locator(".database-dependency-row").count() != 1:
        pytest.fail("database dependency filter did not retain the matching failure")
    tab_panels = (
        ("infrastructure", "dash-infrastructure-metrics"),
        ("reliability", "dash-reliability-summary"),
        ("journeys", "dash-journey-summary"),
    )
    for tab_name, panel_test_id in tab_panels:
        await page.locator(f"#tab-{tab_name}").click()
        panel = page.locator(f"[data-testid={panel_test_id}]")
        if not (await panel.inner_text()).strip():
            pytest.fail(f"{tab_name} tab rendered no retained-data state")
    await page.locator("#tab-hotpaths").click()
    hotpath_rows = page.locator("[data-testid=dash-hotpaths] .hotpath-row")
    if await hotpath_rows.count() != _EXPECTED_HOTPATH_LANES:
        pytest.fail("client hotpath tab did not render the canonical 13-lane inventory")
    for expected in (
        "hot-path-testing",
        "DFT formative assessment",
        "safe-fail-event-path-proof",
        "safe-pass-ingestion-proof",
    ):
        await _require_text(page.locator("#panel-hotpaths"), expected)


async def _verify_mobile_width(page: Page) -> None:
    await page.set_viewport_size({"width": _MOBILE_WIDTH, "height": _MOBILE_HEIGHT})
    viewport = json_object(
        cast(
            "JsonInput",
            await page.evaluate(
                """() => ({
                    innerWidth: window.innerWidth,
                    documentWidth: document.documentElement.scrollWidth,
                    bodyWidth: document.body.scrollWidth,
                })""",
            ),
        ),
    )
    inner_width = int_value(viewport.get("innerWidth"))
    document_width = int_value(viewport.get("documentWidth"))
    body_width = int_value(viewport.get("bodyWidth"))
    if inner_width is None or document_width is None or body_width is None:
        pytest.fail(f"browser returned an invalid viewport receipt: {viewport!r}")
    if document_width > inner_width or body_width > inner_width:
        pytest.fail(f"dashboard overflowed the mobile viewport: {viewport!r}")


async def exercise_actionable_dashboard(
    page: Page,
    base_url: str,
    receipts: BrowserReceipts,
    summary: JsonObject,
) -> None:
    """Verify inventory, incident disclosure, tabs, filtering, and mobile fit."""
    healthy_services = _summary_count(summary, "service_health", "healthy")
    enabled_services = _summary_count(summary, "service_health", "enabled")
    active_domains = _summary_count(summary, "inventory", "active_domains")
    domain_groups = _summary_count(summary, "inventory", "groups")
    expected_service_kpi = f"{healthy_services}/{enabled_services}"
    kpi_expression = (
        f"document.querySelector('#kpi-services').textContent === '{expected_service_kpi}'"
    )
    await page.goto(f"{base_url}/dashboard")
    await page.wait_for_function(kpi_expression)
    tabs = page.locator("[data-testid=dash-tabs] [role=tab]")
    if await tabs.count() != _EXPECTED_TAB_COUNT:
        pytest.fail("dashboard did not render all six requested tabs")
    group_buttons = page.locator("[data-testid=dash-domain-groups] button")
    if await group_buttons.count() != domain_groups + 1:
        pytest.fail("dashboard did not render all production domain groups")
    await _require_text(
        page.locator("#domain-inventory-note"),
        f"{active_domains} monitored domains",
    )
    await _verify_incidents(page)
    await _verify_tabs(page)
    await _verify_mobile_width(page)
    failure_summary = receipts.failure_summary()
    if failure_summary is not None:
        pytest.fail(f"dashboard emitted browser errors: {failure_summary}")
