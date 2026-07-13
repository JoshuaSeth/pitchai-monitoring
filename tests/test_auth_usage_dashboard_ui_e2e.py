from __future__ import annotations

import socket
import threading
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from playwright.async_api import Page, async_playwright

from auth_usage_dashboard.app import create_app
from auth_usage_dashboard.settings import DashboardSettings
from domain_checks.common_check import find_chromium_executable


UTC = timezone.utc


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _fixture_account(
    label: str,
    *,
    availability: str,
    five_used: float,
    weekly_used: float,
    offset_minutes: int,
    weekly_only: bool = False,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    banked = offset_minutes % 4
    daily_usage = [
        {
            "start_date": (now.date() - timedelta(days=6 - day)).isoformat(),
            "tokens": (day + 1) * 12_000 + offset_minutes * 40,
        }
        for day in range(7)
    ]
    reset_details = []
    if banked:
        reset_details.append(
            {
                "reset_type": "weekly",
                "status": "available",
                "granted_at": (now - timedelta(days=2)).isoformat(),
                "expires_at": (
                    now + timedelta(days=8, hours=offset_minutes % 5)
                ).isoformat(),
                "title": "Weekly usage reset",
            }
        )
    rate_limit = {
        "primary_window": {
            "used_percent": five_used,
            "reset_at": (now + timedelta(minutes=offset_minutes)).isoformat(),
            "limit_window_seconds": 18_000,
        },
        "secondary_window": {
            "used_percent": weekly_used,
            "reset_at": (now + timedelta(days=5, hours=offset_minutes % 8)).isoformat(),
            "limit_window_seconds": 604_800,
        },
    }
    if weekly_only:
        rate_limit = {"primary_window": rate_limit["secondary_window"]}
    return {
        "metadata": {
            "account_id": f"internal-{offset_minutes}",
            "label": label,
            "enabled": True,
        },
        "state": {
            "availability": availability,
            "last_probe_at": (now - timedelta(seconds=22)).isoformat(),
            "usage": {
                "email": label,
                "plan_type": "pro",
                "rate_limit": rate_limit,
                "rate_limit_reset_credits": {"available_count": banked},
            },
            "analytics": {
                "last_probe_at": (now - timedelta(seconds=35)).isoformat(),
                "token_usage_updated_at": (now - timedelta(seconds=35)).isoformat(),
                "token_usage": {
                    "summary": {
                        "lifetime_tokens": sum(item["tokens"] for item in daily_usage)
                    },
                    "daily_usage_buckets": daily_usage,
                },
                "reset_credits_updated_at": (now - timedelta(seconds=35)).isoformat(),
                "reset_credits": {"available_count": banked, "credits": reset_details},
                "errors": {},
            },
        },
    }


class FixtureSource:
    def __init__(self) -> None:
        self.accounts = [
            _fixture_account(
                "elise@pitchai.net",
                availability="available",
                five_used=38,
                weekly_used=31,
                offset_minutes=252,
                weekly_only=True,
            ),
            _fixture_account(
                "info@pitchai.net",
                availability="auth_invalid",
                five_used=100,
                weekly_used=45,
                offset_minutes=55,
                weekly_only=True,
            ),
            _fixture_account(
                "jozuasethvanderbijl@gmail.com",
                availability="available",
                five_used=17,
                weekly_used=20,
                offset_minutes=214,
                weekly_only=True,
            ),
            _fixture_account(
                "onboarding.bigi.net",
                availability="available",
                five_used=22,
                weekly_used=32,
                offset_minutes=161,
                weekly_only=True,
            ),
            _fixture_account(
                "sales@pitchai.net",
                availability="auth_invalid",
                five_used=100,
                weekly_used=19,
                offset_minutes=34,
                weekly_only=True,
            ),
            _fixture_account(
                "seth.vanderbijl@pitchai.net",
                availability="available",
                five_used=10,
                weekly_used=25,
                offset_minutes=90,
                weekly_only=True,
            ),
            _fixture_account(
                "support@pitchai.net",
                availability="rate_limited",
                five_used=4,
                weekly_used=100,
                offset_minutes=298,
                weekly_only=True,
            ),
            _fixture_account(
                "svxjvmk78b@privaterelay.appleid.com",
                availability="available",
                five_used=74,
                weekly_used=12,
                offset_minutes=207,
                weekly_only=True,
            ),
        ]

    def read_accounts(self) -> list[dict[str, Any]]:
        return deepcopy(self.accounts)

    def probe_accounts(self, accounts: list[dict[str, Any]]) -> dict[str, str]:
        return {}

    def probe_analytics(self, accounts: list[dict[str, Any]]) -> dict[str, str]:
        return {}

    def close(self) -> None:
        return


@pytest.fixture()
def auth_usage_server(tmp_path: Path) -> str:
    settings = DashboardSettings(
        broker_data_dir=tmp_path,
        broker_url="http://127.0.0.1:38188",
        broker_admin_token="",
        bind_port=_free_port(),
        snapshot_refresh_seconds=300,
        safe_probe_enabled=False,
        probe_on_startup=False,
        require_proxy_auth=False,
    )
    app = create_app(settings, source=FixtureSource())
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=settings.bind_port,
            access_log=False,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{settings.bind_port}"
    with httpx.Client() as client:
        for _ in range(100):
            try:
                if client.get(f"{base_url}/healthz", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        else:
            raise RuntimeError("auth usage dashboard did not start")
    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5)


async def _assert_no_viewport_overflow(page: Page) -> None:
    dimensions = await page.evaluate(
        """() => ({
          viewport: document.documentElement.clientWidth,
          document: document.documentElement.scrollWidth,
          body: document.body.scrollWidth
        })"""
    )
    assert dimensions["document"] <= dimensions["viewport"] + 1
    assert dimensions["body"] <= dimensions["viewport"] + 1


@pytest.mark.asyncio
async def test_dashboard_renders_dense_desktop_and_responsive_mobile(
    auth_usage_server: str,
) -> None:
    executable = find_chromium_executable()
    if not executable:
        pytest.skip("No Chromium/Chrome executable available")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            executable_path=executable,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            desktop = await browser.new_page(viewport={"width": 1440, "height": 1000})
            await desktop.goto(auth_usage_server, wait_until="networkidle")
            await desktop.locator(
                "[data-testid=account-table] tbody tr"
            ).first.wait_for()
            assert (
                await desktop.locator("[data-testid=account-table] tbody tr").count()
                == 8
            )
            onboarding_row = desktop.locator(
                "[data-testid=account-table] tbody tr", has_text="onboarding.bigi.net"
            )
            assert (
                "Provider does not expose 5h"
                in await onboarding_row.locator("td").nth(2).inner_text()
            )
            assert (
                "No 5h reset exposed"
                in await onboarding_row.locator("td").nth(3).inner_text()
            )
            assert "68% left" in await onboarding_row.locator("td").nth(4).inner_text()
            assert (
                "accounts are ready"
                in (await desktop.locator("#decision-title").inner_text()).lower()
            )
            assert await desktop.locator("#runout-grid .runout-cell").count() == 3
            assert "points/hour" in (await desktop.locator("#burn-rate").inner_text())
            assert await desktop.locator("#forecast-grid .forecast-cell").count() == 3
            assert (
                "Weekly headroom"
                in await desktop.locator(
                    "#forecast-grid .forecast-cell"
                ).first.inner_text()
            )
            assert (
                "Unavailable"
                not in await desktop.locator("#forecast-grid").inner_text()
            )
            assert await desktop.locator("#event-list .event-item").count() == 6
            assert await desktop.locator("#usage-chart svg .chart-line").count() == 1
            assert "hourly token usage" in (
                await desktop.locator("#usage-chart").get_attribute("aria-label")
            )
            chart_box = await desktop.locator("#usage-chart").bounding_box()
            assert chart_box is not None and chart_box["width"] > 1300
            assert await desktop.locator("#history-series option").count() == 9
            assert (
                await desktop.locator("#reset-bank-list .reset-bank-row").count() == 6
            )
            await desktop.locator("#reset-bank-toggle").click()
            assert (
                await desktop.locator("#reset-bank-list .reset-bank-row").count() == 7
            )
            await desktop.locator("#history-series").select_option(
                "onboarding.bigi.net"
            )
            assert "onboarding.bigi.net" in (
                await desktop.locator("#usage-chart").get_attribute("aria-label")
            )
            assert await desktop.locator("#mobile-account-list").is_hidden()
            await _assert_no_viewport_overflow(desktop)

            mobile = await browser.new_page(viewport={"width": 390, "height": 844})
            await mobile.goto(auth_usage_server, wait_until="networkidle")
            await mobile.locator(
                "#mobile-account-list .mobile-account"
            ).first.wait_for()
            assert (
                await mobile.locator("#mobile-account-list .mobile-account").count()
                == 8
            )
            onboarding_card = mobile.locator(
                "#mobile-account-list .mobile-account", has_text="onboarding.bigi.net"
            )
            assert "Provider does not expose 5h" in await onboarding_card.inner_text()
            assert "No 5h reset exposed" in await onboarding_card.inner_text()
            assert "68% left" in await onboarding_card.inner_text()
            assert await mobile.locator("#runout-grid .runout-cell").count() == 3
            assert await mobile.locator("#usage-chart svg .chart-line").count() == 1
            assert await mobile.locator(".table-shell").is_hidden()
            await _assert_no_viewport_overflow(mobile)
        finally:
            await browser.close()
