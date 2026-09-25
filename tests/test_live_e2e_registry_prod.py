# Copyright (c) 2026 PitchAI. All rights reserved.
"""Destructive live acceptance tests for the production E2E registry."""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING

import httpx
import pytest

from domain_checks.common_check import find_chromium_executable
from tests.e2e_browser_support import chromium_page
from tests.e2e_registry_ui_support import (
    RegistryUiUpload,
    login_to_registry_ui,
    submit_registry_ui_test,
    verify_invalid_registry_key,
)
from tests.live_e2e_registry_api_support import run_live_api_acceptance
from tests.live_e2e_registry_support import (
    admin_token,
    base_url,
    create_tenant_api_key,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.live

if os.getenv("RUN_LIVE_E2E_REGISTRY_TESTS") != "1":
    pytest.skip(
        "Set RUN_LIVE_E2E_REGISTRY_TESTS=1 to run live e2e-registry acceptance tests",
        allow_module_level=True,
    )


@pytest.mark.asyncio
async def test_live_e2e_registry_api_pass_fail_artifacts_and_isolation() -> None:
    """Verify live runner outcomes, artifacts, and tenant isolation.

    Raises:
        AssertionError: If the configured live URL is not HTTP or HTTPS.
    """
    if not base_url().startswith(("http://", "https://")):
        message = "live registry base URL must use HTTP or HTTPS"
        raise AssertionError(message)
    await run_live_api_acceptance()


@pytest.mark.asyncio
async def test_live_e2e_registry_ui_login_and_upload(tmp_path: Path) -> None:
    """Verify live login and upload through the production registry UI."""
    registry_url = base_url()
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")

    async with httpx.AsyncClient(
        headers={"User-Agent": "PitchAI Live E2E Registry UI Test"},
    ) as client:
        tenant_token = await create_tenant_api_key(
            client,
            registry_url=registry_url,
            admin=admin_token(),
            tenant_name=f"live-ui-{uuid.uuid4().hex[:10]}",
            key_name="ui-key",
        )

    test_path = tmp_path / "live_ui_test.py"
    test_path.write_text(
        "async def run(page, base_url, artifacts_dir):\n"
        "    await page.goto(base_url.rstrip('/') + '/', wait_until='domcontentloaded')\n"
        "    title = await page.title()\n"
        "    if 'Deplanbook' not in (title or ''):\n"
        "        raise AssertionError('expected Deplanbook page title')\n",
        encoding="utf-8",
    )

    async with chromium_page(chromium_path) as page:
        await verify_invalid_registry_key(page, base_url=registry_url)
        await login_to_registry_ui(page, token=tenant_token)
        await submit_registry_ui_test(
            page,
            upload=RegistryUiUpload(
                name=f"live_ui_created_{uuid.uuid4().hex[:6]}",
                base_url="https://deplanbook.com",
                interval_seconds="3600",
                test_path=test_path,
            ),
        )
