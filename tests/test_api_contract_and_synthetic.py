from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
from playwright.async_api import async_playwright

from domain_checks.common_check import find_chromium_executable
from domain_checks.metrics_api_contract import run_api_contract_checks
from domain_checks.metrics_synthetic import run_synthetic_transactions


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _send(self, status: int, headers: dict[str, str], body: bytes) -> None:
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            payload = {"status": "healthy", "timestamp": "t-1", "runtime_config_version": "v1"}
            body = json.dumps(payload).encode("utf-8")
            self._send(200, {"Content-Type": "application/json"}, body)
            return

        if self.path == "/health_bad":
            payload = {"status": "healthy"}
            body = json.dumps(payload).encode("utf-8")
            self._send(200, {"Content-Type": "application/json"}, body)
            return

        if self.path == "/page":
            html = (
                "<!doctype html><html><head><title>Page</title></head>"
                "<body><a href=\"/next\" id=\"go\">Next</a></body></html>"
            )
            self._send(200, {"Content-Type": "text/html; charset=utf-8"}, html.encode("utf-8"))
            return

        if self.path == "/next":
            html = "<!doctype html><html><head><title>Next</title></head><body><h1>Next</h1></body></html>"
            self._send(200, {"Content-Type": "text/html; charset=utf-8"}, html.encode("utf-8"))
            return

        self._send(404, {"Content-Type": "text/plain; charset=utf-8"}, b"not found")


@pytest.fixture(scope="module")
def local_server_base_url() -> str:
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    host, port = httpd.server_address
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()


@pytest.mark.asyncio
async def test_api_contract_checks_ok_and_fail(local_server_base_url: str) -> None:
    checks_ok = [
        {
            "name": "health",
            "path": "/health",
            "expected_status_codes": [200],
            "expected_content_type_contains": "application/json",
            "json_paths_required": ["status", "timestamp", "runtime_config_version"],
            "json_paths_equal": {"status": "healthy"},
        }
    ]

    checks_bad = [
        {
            "name": "health_bad",
            "path": "/health_bad",
            "expected_status_codes": [200],
            "expected_content_type_contains": "application/json",
            "json_paths_required": ["timestamp"],
        }
    ]

    async with httpx.AsyncClient() as client:
        ok_res = await run_api_contract_checks(
            http_client=client,
            domain="svc",
            base_url=local_server_base_url,
            checks=checks_ok,
            timeout_seconds=2.0,
        )
        assert ok_res and ok_res[0].ok is True

        bad_res = await run_api_contract_checks(
            http_client=client,
            domain="svc",
            base_url=local_server_base_url,
            checks=checks_bad,
            timeout_seconds=2.0,
        )
        assert bad_res and bad_res[0].ok is False
        assert bad_res[0].error in {"missing_json_paths", "json_value_mismatch"} or (bad_res[0].error or "").startswith("missing_json_paths")


@pytest.mark.asyncio
async def test_synthetic_transactions_basic_flow(local_server_base_url: str) -> None:
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            tx = [
                {
                    "name": "click_next",
                    "steps": [
                        {"type": "goto", "url": f"{local_server_base_url}/page"},
                        {"type": "click", "selector": "#go"},
                        {"type": "expect_url_contains", "value": "/next"},
                    ],
                }
            ]
            res = await run_synthetic_transactions(
                domain="svc",
                base_url=local_server_base_url,
                browser=browser,
                transactions=tx,
                timeout_seconds=5.0,
            )
            assert res and res[0].ok is True
        finally:
            await browser.close()

