# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock the rendered authentication usage dashboard experience."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import httpx
import pytest
import uvicorn
from fastapi import status
from playwright.async_api import async_playwright

from auth_usage_dashboard.app import create_app
from auth_usage_dashboard.settings import DashboardSettings
from domain_checks.common_check import find_chromium_executable
from tests.auth_usage_ui_assertions import exercise_dashboard
from tests.auth_usage_ui_support import FixtureSource, free_port

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


def _dashboard_ready(client: httpx.Client, base_url: str) -> bool:
    """Return whether the local UI server is accepting health requests."""
    try:
        return (
            client.get(f"{base_url}/healthz", timeout=1).status_code
            == status.HTTP_200_OK
        )
    except httpx.HTTPError:
        return False


@pytest.fixture(name="auth_usage_server")
def auth_usage_server_fixture(tmp_path: Path) -> Generator[str]:
    """Serve the dashboard fixture on one isolated local port.

    Yields:
        Each generated value.

    Raises:
        RuntimeError: If the operation cannot satisfy its runtime contract.

    """
    settings = DashboardSettings(
        broker_data_dir=tmp_path,
        broker_url="http://127.0.0.1:38188",
        broker_admin_token="",
        bind_port=free_port(),
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
        ),
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{settings.bind_port}"
    with httpx.Client() as client:
        for _ in range(100):
            if _dashboard_ready(client, base_url):
                break
            time.sleep(0.05)
        else:
            msg = "auth usage dashboard did not start"
            raise RuntimeError(msg)
    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.asyncio
async def test_dashboard_renders_dense_desktop_and_responsive_mobile(
    auth_usage_server: str,
) -> None:
    """Render complete desktop and mobile dashboard experiences."""
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
            await exercise_dashboard(browser, auth_usage_server)
        finally:
            await browser.close()
