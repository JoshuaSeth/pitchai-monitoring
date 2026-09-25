# Copyright (c) 2026 PitchAI. All rights reserved.
"""Browser acceptance coverage for registry login and test upload."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from domain_checks.common_check import find_chromium_executable
from e2e_registry.models import require_json_object, require_text
from tests.e2e_browser_support import chromium_page
from tests.e2e_registry_runner_support import json_payload
from tests.e2e_registry_ui_support import (
    RegistryUiUpload,
    login_to_registry_ui,
    submit_registry_ui_test,
    verify_invalid_registry_key,
    verify_registry_test_detail,
)

if TYPE_CHECKING:
    from pathlib import Path

    from tests.e2e_registry_server_support import RegistryServer

pytest_plugins = ["tests.e2e_registry_server_support"]


async def _create_tenant_token(server: RegistryServer) -> str:
    async with httpx.AsyncClient(base_url=server.base_url) as client:
        tenant_payload = json_payload(
            await client.post(
                "/api/v1/admin/tenants",
                headers={"Authorization": f"Bearer {server.settings.admin_token}"},
                json={"name": "tenant-ui"},
                timeout=5.0,
            ),
            label="UI tenant",
        )
        tenant = require_json_object(tenant_payload.get("tenant"), label="UI tenant")
        tenant_id = require_text(tenant.get("id"), label="UI tenant id")
        key_payload = json_payload(
            await client.post(
                "/api/v1/admin/api_keys",
                headers={"Authorization": f"Bearer {server.settings.admin_token}"},
                json={"tenant_id": tenant_id, "name": "ui-key"},
                timeout=5.0,
            ),
            label="UI API key",
        )
    return require_text(key_payload.get("token"), label="UI tenant token")


@pytest.mark.asyncio
async def test_registry_ui_login_and_upload_flow(
    registry_server: RegistryServer,
    local_site_base_url: str,
    tmp_path: Path,
) -> None:
    """Verify invalid login, valid login, upload, listing, and source detail."""
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")
    token = await _create_tenant_token(registry_server)
    test_path = tmp_path / "ui_test.py"
    test_path.write_text(
        "async def run(page, base_url, artifacts_dir):\n"
        "    await page.goto(base_url.rstrip('/') + '/', "
        "wait_until='domcontentloaded')\n"
        "    body = await page.evaluate(\"() => document.body?.innerText || ''\")\n"
        "    if 'Everything is fine' not in (body or ''):\n"
        "        raise AssertionError('expected fixture text')\n",
        encoding="utf-8",
    )

    async with chromium_page(chromium_path) as page:
        await verify_invalid_registry_key(page, base_url=registry_server.base_url)
        await login_to_registry_ui(page, token=token)
        test_links = await submit_registry_ui_test(
            page,
            upload=RegistryUiUpload(
                name="ui_created_test",
                base_url=local_site_base_url,
                interval_seconds="300",
                test_path=test_path,
            ),
        )
        await verify_registry_test_detail(
            page,
            test_links=test_links,
            expected_name="ui_created_test",
        )
