from __future__ import annotations

import asyncio
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
from playwright.async_api import async_playwright

from domain_checks.common_check import DomainCheckSpec, SelectorCheck, find_chromium_executable, http_get_check, browser_check


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        routes: dict[str, tuple[int, dict[str, str], str]] = {
            "/ok": (
                200,
                {"Content-Type": "text/html; charset=utf-8"},
                (
                    "<!doctype html><html><head><title>OK Page</title></head>"
                    "<body><nav>nav</nav><h1>Everything is fine</h1></body></html>"
                ),
            ),
            "/maintenance": (
                200,
                {"Content-Type": "text/html; charset=utf-8"},
                (
                    "<!doctype html><html><head><title>Maintenance</title></head>"
                    "<body><h1>Maintenance</h1><p>We'll be back soon.</p></body></html>"
                ),
            ),
            "/script_contains_forbidden": (
                200,
                {"Content-Type": "text/html; charset=utf-8"},
                (
                    "<!doctype html><html><head><title>OK Page</title></head>"
                    "<body><nav>nav</nav><h1>Everything is fine</h1>"
                    "<script>var maintenanceMode = false;</script></body></html>"
                ),
            ),
            "/missing_nav": (
                200,
                {"Content-Type": "text/html; charset=utf-8"},
                "<!doctype html><html><head><title>OK Page</title></head><body><h1>No nav</h1></body></html>",
            ),
            "/bad_gateway": (
                502,
                {"Content-Type": "text/plain; charset=utf-8"},
                "Bad Gateway",
            ),
        }

        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
            return

        status, headers, body = routes.get(
            self.path,
            (404, {"Content-Type": "text/plain; charset=utf-8"}, "Not Found"),
        )
        body_bytes = body.encode("utf-8")
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)


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
async def test_http_get_ok(local_server_base_url: str) -> None:
    spec = DomainCheckSpec(domain="local", url=f"{local_server_base_url}/ok", http_timeout_seconds=5.0)
    async with httpx.AsyncClient() as client:
        ok, details = await http_get_check(spec, client)
    assert ok is True
    assert details["status_code"] == 200
    assert details["forbidden_hits"] == []
    assert isinstance(details.get("http_elapsed_ms"), (int, float))
    assert float(details["http_elapsed_ms"]) >= 0


@pytest.mark.asyncio
async def test_http_get_redirect_is_ok(local_server_base_url: str) -> None:
    spec = DomainCheckSpec(domain="local", url=f"{local_server_base_url}/redirect", http_timeout_seconds=5.0)
    async with httpx.AsyncClient() as client:
        ok, details = await http_get_check(spec, client)
    assert ok is True
    assert details["status_code"] == 200
    assert str(details["final_url"]).endswith("/ok")
    assert isinstance(details.get("http_elapsed_ms"), (int, float))
    assert float(details["http_elapsed_ms"]) >= 0


@pytest.mark.asyncio
async def test_http_get_expected_final_host_suffix_enforced(local_server_base_url: str) -> None:
    async with httpx.AsyncClient() as client:
        spec_ok = DomainCheckSpec(
            domain="local",
            url=f"{local_server_base_url}/ok",
            http_timeout_seconds=5.0,
            expected_final_host_suffix="127.0.0.1",
        )
        ok, details = await http_get_check(spec_ok, client)
        assert ok is True
        assert details["final_host"] == "127.0.0.1"
        assert details["final_host_ok"] is True

        spec_bad = DomainCheckSpec(
            domain="local",
            url=f"{local_server_base_url}/ok",
            http_timeout_seconds=5.0,
            expected_final_host_suffix="example.com",
        )
        ok, details = await http_get_check(spec_bad, client)
        assert ok is False
        assert details["final_host"] == "127.0.0.1"
        assert details["final_host_ok"] is False


@pytest.mark.asyncio
async def test_http_get_maintenance_detected(local_server_base_url: str) -> None:
    spec = DomainCheckSpec(domain="local", url=f"{local_server_base_url}/maintenance", http_timeout_seconds=5.0)
    async with httpx.AsyncClient() as client:
        ok, details = await http_get_check(spec, client)
    assert ok is False
    assert details["status_code"] == 200
    assert any("maintenance" in h for h in details["forbidden_hits"])
    assert isinstance(details.get("http_elapsed_ms"), (int, float))
    assert float(details["http_elapsed_ms"]) >= 0


@pytest.mark.asyncio
async def test_http_get_ignores_script_text(local_server_base_url: str) -> None:
    spec = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/script_contains_forbidden",
        http_timeout_seconds=5.0,
    )
    async with httpx.AsyncClient() as client:
        ok, details = await http_get_check(spec, client)
    assert ok is True
    assert details["status_code"] == 200
    assert details["forbidden_hits"] == []
    assert isinstance(details.get("http_elapsed_ms"), (int, float))
    assert float(details["http_elapsed_ms"]) >= 0


@pytest.mark.asyncio
async def test_http_get_bad_gateway_fails(local_server_base_url: str) -> None:
    spec = DomainCheckSpec(domain="local", url=f"{local_server_base_url}/bad_gateway", http_timeout_seconds=5.0)
    async with httpx.AsyncClient() as client:
        ok, details = await http_get_check(spec, client)
    assert ok is False
    assert details["status_code"] == 502
    assert isinstance(details.get("http_elapsed_ms"), (int, float))
    assert float(details["http_elapsed_ms"]) >= 0


@pytest.mark.asyncio
async def test_http_get_allows_explicit_status_codes(local_server_base_url: str) -> None:
    spec = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/bad_gateway",
        http_timeout_seconds=5.0,
        allowed_status_codes=[502],
        forbidden_text_any=[],
    )
    async with httpx.AsyncClient() as client:
        ok, details = await http_get_check(spec, client)
    assert ok is True
    assert details["status_code"] == 502
    assert isinstance(details.get("http_elapsed_ms"), (int, float))
    assert float(details["http_elapsed_ms"]) >= 0


@pytest.mark.asyncio
async def test_browser_check_ok(local_server_base_url: str) -> None:
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")

    spec = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/ok",
        expected_title_contains="OK Page",
        required_selectors_all=[SelectorCheck(selector="nav", state="visible")],
        browser_timeout_seconds=5.0,
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            ok, details = await browser_check(spec, browser)
        finally:
            await browser.close()

    assert ok is True
    assert details["title_ok"] is True
    assert details["missing_selectors_all"] == []
    assert isinstance(details.get("browser_elapsed_ms"), (int, float))
    assert float(details["browser_elapsed_ms"]) >= 0


@pytest.mark.asyncio
async def test_browser_check_expected_final_host_suffix_enforced(local_server_base_url: str) -> None:
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")

    spec_ok = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/ok",
        expected_final_host_suffix="127.0.0.1",
        browser_timeout_seconds=5.0,
    )

    spec_bad = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/ok",
        expected_final_host_suffix="example.com",
        browser_timeout_seconds=5.0,
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            ok, details = await browser_check(spec_ok, browser)
            assert ok is True
            assert details["final_host"] == "127.0.0.1"
            assert details["final_host_ok"] is True

            ok, details = await browser_check(spec_bad, browser)
            assert ok is False
            assert details["final_host"] == "127.0.0.1"
            assert details["final_host_ok"] is False
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_browser_check_title_mismatch_fails(local_server_base_url: str) -> None:
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")

    spec = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/ok",
        expected_title_contains="Some Other Title",
        browser_timeout_seconds=5.0,
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            ok, details = await browser_check(spec, browser)
        finally:
            await browser.close()

    assert ok is False
    assert details["title_ok"] is False


@pytest.mark.asyncio
async def test_browser_check_required_any_selector(local_server_base_url: str) -> None:
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")

    spec = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/ok",
        required_selectors_any=[
            SelectorCheck(selector="#does-not-exist", state="attached"),
            SelectorCheck(selector="nav", state="visible"),
        ],
        browser_timeout_seconds=5.0,
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            ok, details = await browser_check(spec, browser)
        finally:
            await browser.close()

    assert ok is True
    assert details["required_any_ok"] is True


@pytest.mark.asyncio
async def test_browser_check_required_any_missing_fails(local_server_base_url: str) -> None:
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")

    spec = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/ok",
        required_selectors_any=[
            SelectorCheck(selector="#does-not-exist", state="attached"),
            SelectorCheck(selector="#also-missing", state="attached"),
        ],
        browser_timeout_seconds=5.0,
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            ok, details = await browser_check(spec, browser)
        finally:
            await browser.close()

    assert ok is False
    assert details["required_any_ok"] is False


@pytest.mark.asyncio
async def test_browser_check_required_any_timeout_not_multiplied(local_server_base_url: str) -> None:
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")

    spec = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/ok",
        required_selectors_any=[
            SelectorCheck(selector="#missing-1", state="attached"),
            SelectorCheck(selector="#missing-2", state="attached"),
            SelectorCheck(selector="#missing-3", state="attached"),
        ],
        browser_timeout_seconds=1.0,
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            started = time.monotonic()
            ok, details = await browser_check(spec, browser)
            elapsed = time.monotonic() - started
        finally:
            await browser.close()

    assert ok is False
    assert details["required_any_ok"] is False
    # This should be ~1x timeout, not N * timeout. Allow some slack for CI scheduling jitter.
    assert elapsed < 3.0


@pytest.mark.asyncio
async def test_browser_check_maintenance_fails(local_server_base_url: str) -> None:
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")

    spec = DomainCheckSpec(domain="local", url=f"{local_server_base_url}/maintenance", browser_timeout_seconds=5.0)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            ok, details = await browser_check(spec, browser)
        finally:
            await browser.close()

    assert ok is False
    assert any("maintenance" in h for h in details["forbidden_hits"])
    assert isinstance(details.get("browser_elapsed_ms"), (int, float))
    assert float(details["browser_elapsed_ms"]) >= 0


@pytest.mark.asyncio
async def test_browser_check_missing_selector_fails(local_server_base_url: str) -> None:
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")

    spec = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/missing_nav",
        required_selectors_all=[SelectorCheck(selector="nav", state="visible")],
        browser_timeout_seconds=5.0,
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            ok, details = await browser_check(spec, browser)
        finally:
            await browser.close()

    assert ok is False
    assert "nav" in details["missing_selectors_all"]


@pytest.mark.asyncio
async def test_browser_check_does_not_raise_if_browser_closes_mid_check(local_server_base_url: str) -> None:
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")

    spec = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/ok",
        required_selectors_all=[SelectorCheck(selector="#definitely-missing", state="attached")],
        browser_timeout_seconds=10.0,
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        task = asyncio.create_task(browser_check(spec, browser))
        await asyncio.sleep(0.2)
        try:
            await browser.close()
        except Exception:
            pass
        ok, details = await task

    assert ok is False
    assert details.get("browser_infra_error") is True
