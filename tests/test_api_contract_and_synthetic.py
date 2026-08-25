from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
from playwright.async_api import async_playwright

from domain_checks.common_check import find_chromium_executable
from domain_checks.main import (
    _build_api_contract_alert_message,
    _build_api_contract_delivery_receipt_fields,
)
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
        if self.path == "/not_ready":
            body = json.dumps(
                {
                    "status": "not_ready",
                    "service": "deplanbook-play",
                    "commit": "a" * 40,
                    "failure_class": "database_authentication",
                    "private_detail": "must-not-propagate",
                }
            ).encode("utf-8")
            self._send(503, {"Content-Type": "application/json"}, body)
            return

        if self.path == "/private":
            expected = "Bearer secret-token"
            got = self.headers.get("Authorization") or ""
            if got != expected:
                body = json.dumps({"status": "unauthorized"}).encode("utf-8")
                self._send(401, {"Content-Type": "application/json"}, body)
                return
            body = json.dumps({"status": "ok"}).encode("utf-8")
            self._send(200, {"Content-Type": "application/json"}, body)
            return

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
async def test_api_contract_captures_only_safe_failure_class_for_internal_alert(
    local_server_base_url: str,
) -> None:
    async with httpx.AsyncClient() as client:
        results = await run_api_contract_checks(
            http_client=client,
            domain="deplanbook.com",
            base_url=local_server_base_url,
            checks=[
                {
                    "name": "database_readiness",
                    "service": "deplanbook-play",
                    "path": "/not_ready",
                    "expected_status_codes": [200],
                    "failure_class_json_path": "failure_class",
                    "application_commit_json_path": "commit",
                }
            ],
            timeout_seconds=2.0,
        )

    assert len(results) == 1
    result = results[0]
    assert result.ok is False
    assert result.service == "deplanbook-play"
    assert result.details["failure_class"] == "database_authentication"
    assert result.details["application_commit"] == "a" * 40
    assert "must-not-propagate" not in json.dumps(result.details)
    alert = _build_api_contract_alert_message(
        failures=results,
        down_after_failures=1,
        fail_streak=1,
    )
    assert "service=deplanbook-play" in alert
    assert "failure_class=database_authentication" in alert
    assert "must-not-propagate" not in alert

    receipt = _build_api_contract_delivery_receipt_fields(
        failures=results,
        responses=[{"ok": True, "result": {"message_id": 8123, "chat": {"id": -9}}}],
        sent_ok=True,
        monitor_observed_at=1_777_000_000.0,
        monitor_commit="b" * 40,
        telegram_chat_id="-9",
    )
    assert receipt == {
        "schema_version": 1,
        "domain": "deplanbook.com",
        "service": "deplanbook-play",
        "failure_class": "database_authentication",
        "application_commit": "a" * 40,
        "monitor_commit": "b" * 40,
        "monitor_observed_at": 1_777_000_000.0,
        "channel": "internal_telegram",
        "destination_scope": "pitchai_internal",
        "destination_sha256": (
            "6cdb894be74e95f29940d7eb84bba16f2a221ea3656789f9b748e592212fec0b"
        ),
        "telegram_message_ids": [8123],
        "delivery_status": "sent",
        "external_message_sent": False,
    }

    assert (
        _build_api_contract_delivery_receipt_fields(
            failures=results,
            responses=[{"ok": False, "error": "network"}],
            sent_ok=False,
            monitor_observed_at=1_777_000_000.0,
            monitor_commit="b" * 40,
            telegram_chat_id="-100-private",
        )
        is None
    )

    assert (
        _build_api_contract_delivery_receipt_fields(
            failures=results,
            responses=[
                {"ok": True, "result": {"message_id": 8123, "chat": {"id": -8}}}
            ],
            sent_ok=True,
            monitor_observed_at=1_777_000_000.0,
            monitor_commit="b" * 40,
            telegram_chat_id="-9",
        )
        is None
    )

    result.details["failure_class"] = "database authentication"
    assert (
        _build_api_contract_delivery_receipt_fields(
            failures=results,
            responses=[
                {"ok": True, "result": {"message_id": 8123, "chat": {"id": -9}}}
            ],
            sent_ok=True,
            monitor_observed_at=1_777_000_000.0,
            monitor_commit="b" * 40,
            telegram_chat_id="-9",
        )
        is None
    )


@pytest.mark.asyncio
async def test_api_contract_paths_resolve_from_origin_when_page_url_has_a_path(
    local_server_base_url: str,
) -> None:
    page_url = f"{local_server_base_url}/chat/demo/start?floating=false&mode=codex"
    checks = [
        {
            "name": "health",
            "path": "/health",
            "expected_status_codes": [200],
            "expected_content_type_contains": "application/json",
            "json_paths_equal": {"status": "healthy"},
        }
    ]

    async with httpx.AsyncClient() as client:
        results = await run_api_contract_checks(
            http_client=client,
            domain="svc",
            base_url=page_url,
            checks=checks,
            timeout_seconds=2.0,
        )

    assert results and results[0].ok is True
    assert results[0].url == f"{local_server_base_url}/health"
    assert results[0].details["final_url"] == f"{local_server_base_url}/health"


@pytest.mark.asyncio
async def test_api_contract_can_explicitly_skip_content_type_validation(local_server_base_url: str) -> None:
    async with httpx.AsyncClient() as client:
        result = await run_api_contract_checks(
            http_client=client,
            domain="svc",
            base_url=local_server_base_url,
            checks=[
                {
                    "name": "plain_page",
                    "path": "/page",
                    "expected_status_codes": [200],
                    "expected_content_type_contains": None,
                }
            ],
            timeout_seconds=2.0,
        )

    assert result and result[0].ok is True


@pytest.mark.asyncio
async def test_api_contract_substitutes_header_env_without_logging_secret(
    local_server_base_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRIVATE_MONITOR_TOKEN", "secret-token")
    checks = [
        {
            "name": "private",
            "path": "/private",
            "headers": {"Authorization": "Bearer ${PRIVATE_MONITOR_TOKEN}"},
            "expected_status_codes": [200],
            "json_paths_equal": {"status": "ok"},
        }
    ]

    async with httpx.AsyncClient() as client:
        res = await run_api_contract_checks(
            http_client=client,
            domain="svc",
            base_url=local_server_base_url,
            checks=checks,
            timeout_seconds=2.0,
        )

    assert res and res[0].ok is True
    assert "secret-token" not in json.dumps(res[0].details)


@pytest.mark.asyncio
async def test_api_contract_missing_header_env_fails_without_secret_value(
    local_server_base_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISSING_MONITOR_TOKEN", raising=False)
    checks = [
        {
            "name": "private",
            "path": "/private",
            "headers": {"Authorization": "Bearer ${MISSING_MONITOR_TOKEN}"},
            "expected_status_codes": [200],
            "json_paths_equal": {"status": "ok"},
        }
    ]

    async with httpx.AsyncClient() as client:
        res = await run_api_contract_checks(
            http_client=client,
            domain="svc",
            base_url=local_server_base_url,
            checks=checks,
            timeout_seconds=2.0,
        )

    assert res and res[0].ok is False
    assert "missing_env_secrets" in (res[0].error or "")
    assert "Bearer" not in json.dumps(res[0].details)


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
