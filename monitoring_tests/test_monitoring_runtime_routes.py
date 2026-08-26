# Copyright (c) 2026 PitchAI. All rights reserved.
"""Exercise live domain check routing and Telegram policy boundaries."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

import pytest

import domain_checks.main as monitoring
from domain_checks.inventory import DomainAlertPolicy
from domain_checks.main import (
    DomainEntryConfig,
    check_one_domain,
    load_domain_spec,
)
from monitoring_test_support.inventory import (
    EXPECTED_ACTIVE_DOMAINS,
    EXPECTED_DASHBOARD_ONLY_DOMAINS,
    production_domains,
)

if TYPE_CHECKING:
    import httpx
    from playwright.async_api import Browser

    from domain_checks.common_check import DomainCheckSpec
    from domain_checks.json_types import JsonObject


def test_domain_telegram_policy_suppresses_dashboard_only_and_routes_critical() -> None:
    """Mark only critical production domains as eligible for Telegram."""
    for domain in sorted(EXPECTED_DASHBOARD_ONLY_DOMAINS):
        entry = DomainEntryConfig(
            domain=domain,
            raw_entry={},
            alert_policy=DomainAlertPolicy(
                telegram="dashboard-only",
                reason="intentionally unused or noncritical surface",
            ),
        )
        if entry.routes_telegram:
            pytest.fail(f"dashboard-only domain is eligible for Telegram: {domain}")

    critical_entry = DomainEntryConfig(
        domain="pitchai.net",
        raw_entry={},
        alert_policy=DomainAlertPolicy(telegram="critical"),
    )
    if not critical_entry.routes_telegram:
        pytest.fail("critical production domain is not eligible for Telegram")


@pytest.mark.asyncio
async def test_every_inventory_domain_enters_http_and_browser_check_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise every active domain through its configured runtime check path."""
    entries = production_domains()
    specs = [load_domain_spec(entry) for entry in entries]
    http_checked: list[str] = []
    browser_checked: list[str] = []

    async def fake_http(
        spec: DomainCheckSpec,
        _client: httpx.AsyncClient,
    ) -> tuple[bool, JsonObject]:
        await asyncio.sleep(0)
        http_checked.append(spec.domain)
        return True, {"status_code": 200}

    async def fake_browser(
        spec: DomainCheckSpec,
        _browser: Browser,
    ) -> tuple[bool, JsonObject]:
        await asyncio.sleep(0)
        browser_checked.append(spec.domain)
        return True, {"http_status": 200}

    monkeypatch.setattr(monitoring, "http_get_check", fake_http)
    monkeypatch.setattr(monitoring, "browser_check", fake_browser)
    semaphore = asyncio.Semaphore(4)
    checks = [
        check_one_domain(
            spec,
            cast("httpx.AsyncClient", object()),
            cast("Browser", object()),
            browser_semaphore=semaphore,
        )
        for spec in specs
    ]
    results = await asyncio.gather(*checks)

    result_domains = [result.domain for result in results]
    if frozenset(result_domains) != EXPECTED_ACTIVE_DOMAINS:
        pytest.fail("not every active domain returned a runtime check result")
    if frozenset(http_checked) != EXPECTED_ACTIVE_DOMAINS:
        pytest.fail("not every active domain entered the HTTP check path")
    browser_enabled_specs = [spec for spec in specs if spec.browser_enabled]
    expected_browser_domains = {spec.domain for spec in browser_enabled_specs}
    if set(browser_checked) != expected_browser_domains:
        pytest.fail("browser-enabled inventory did not enter the browser check path")
    unsuccessful_results = [result for result in results if not result.ok]
    failed_results = [result.domain for result in unsuccessful_results]
    if failed_results:
        pytest.fail(f"runtime pipeline fixture returned failures: {failed_results!r}")
