from __future__ import annotations

import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import pytest
import uvicorn
from playwright.async_api import async_playwright

from domain_checks.common_check import find_chromium_executable
from e2e_registry.app import create_app
from e2e_registry.settings import RegistrySettings


def _pick_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


class _SiteHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        status = 200
        body = (
            "<!doctype html><html><head><title>OK Page</title></head>"
            "<body><nav>nav</nav><h1>Everything is fine</h1></body></html>"
        )
        body_bytes = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)


@pytest.fixture(scope="module")
def local_site_base_url() -> str:
    httpd = HTTPServer(("127.0.0.1", 0), _SiteHandler)
    host, port = httpd.server_address
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()


@pytest.fixture()
def registry_ui_server(tmp_path: Path):
    db_path = tmp_path / "e2e-registry.db"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    settings = RegistrySettings(
        db_path=str(db_path),
        artifacts_dir=str(artifacts_dir),
        admin_token="adm_ui_token",
        monitor_token="mon_ui_token",
        runner_token="run_ui_token",
        alerts_enabled=False,
        dispatch_enabled=False,
        public_base_url="",
    )
    app = create_app(settings)
    port = _pick_free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"

    with httpx.Client() as client:
        for _ in range(80):
            try:
                r = client.get(f"{base_url}/health", timeout=1.0)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.05)
        else:
            raise RuntimeError("registry server did not start")

        r = client.post(
            f"{base_url}/api/v1/admin/tenants",
            headers={"Authorization": f"Bearer {settings.admin_token}"},
            json={"name": "tenant-ui"},
            timeout=5.0,
        )
        r.raise_for_status()
        tenant_id = r.json()["tenant"]["id"]

        r = client.post(
            f"{base_url}/api/v1/admin/api_keys",
            headers={"Authorization": f"Bearer {settings.admin_token}"},
            json={"tenant_id": tenant_id, "name": "ui-key"},
            timeout=5.0,
        )
        r.raise_for_status()
        tenant_token = r.json()["token"]

    try:
        yield {"base_url": base_url, "tenant_token": tenant_token}
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.asyncio
async def test_registry_ui_login_and_upload_flow(
    registry_ui_server: dict[str, str],
    local_site_base_url: str,
    tmp_path: Path,
) -> None:
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")

    base_url = registry_ui_server["base_url"]
    token = registry_ui_server["tenant_token"]

    definition_path = tmp_path / "flow.yaml"
    definition_path.write_text(
        "\n".join(
            [
                "name: ui_created_test",
                "steps:",
                "  - type: goto",
                "    url: /",
                "  - type: expect_text",
                "    text: Everything is fine",
                "",
            ]
        ),
        encoding="utf-8",
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context()
        page = await context.new_page()
        try:
            # Negative path: invalid key should show an error.
            await page.goto(f"{base_url}/ui/login")
            await page.locator("[data-testid=login-api-key]").fill("invalid-key")
            await page.locator("[data-testid=login-submit]").click()
            await page.wait_for_selector("[data-testid=login-error]")
            err = await page.locator("[data-testid=login-error]").inner_text()
            assert "Invalid" in err

            # Happy path: login succeeds and shows tests page.
            await page.locator("[data-testid=login-api-key]").fill(token)
            await page.locator("[data-testid=login-submit]").click()
            await page.wait_for_selector("[data-testid=tests-title]")
            assert await page.locator("[data-testid=tests-title]").inner_text() == "Tests"

            # Upload a StepFlow definition.
            await page.locator("[data-testid=nav-upload]").click()
            await page.wait_for_selector("[data-testid=upload-title]")
            await page.locator("[data-testid=upload-name]").fill("ui_created_test")
            await page.locator("[data-testid=upload-base-url]").fill(local_site_base_url)
            await page.locator("[data-testid=upload-interval]").fill("300")
            await page.set_input_files("[data-testid=upload-file]", str(definition_path))
            await page.locator("[data-testid=upload-submit]").click()
            await page.wait_for_selector("[data-testid=upload-msg]")

            # Verify the new test appears in the list.
            await page.locator("[data-testid=nav-tests]").click()
            await page.wait_for_selector("[data-testid=tests-table]")
            assert await page.locator("a[data-testid=test-link]", has_text="ui_created_test").count() >= 1

            # Drill into the test detail page and verify stable elements exist.
            await page.locator("a[data-testid=test-link]", has_text="ui_created_test").first.click()
            await page.wait_for_selector("[data-testid=test-detail-title]")
            title = await page.locator("[data-testid=test-detail-title]").inner_text()
            assert "ui_created_test" in title
            # This would fail if the page accidentally renders without the definition section.
            assert await page.locator("[data-testid=definition-json]").count() == 1
        finally:
            await context.close()
            await browser.close()
