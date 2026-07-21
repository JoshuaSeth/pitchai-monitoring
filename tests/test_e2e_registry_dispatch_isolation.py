from __future__ import annotations

import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import pytest

from e2e_registry import db as dbm
from e2e_registry.alerts import maybe_dispatch_failure_investigation
from e2e_registry.app import create_app
from e2e_registry.settings import RegistrySettings


class _SsoRedirectHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def do_POST(self) -> None:  # noqa: N802
        self.send_response(302)
        self.send_header("Location", "https://auth.pitchai.test/oauth2/start?rd=https%3A%2F%2Fdispatch.pitchai.test")
        self.end_headers()


@pytest.fixture()
def sso_redirect_base_url() -> str:
    server = HTTPServer(("127.0.0.1", 0), _SsoRedirectHandler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{port}/dispatch-token-in-url"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _settings(tmp_path: Path, *, dispatch_base_url: str) -> RegistrySettings:
    return RegistrySettings(
        db_path=str(tmp_path / "e2e-registry.db"),
        artifacts_dir=str(tmp_path / "artifacts"),
        tests_dir=str(tmp_path / "tests"),
        runner_token="runner-token",
        alerts_enabled=False,
        dispatch_enabled=True,
        dispatch_base_url=dispatch_base_url,
        dispatch_token="dispatch-token-in-url",
        public_base_url="https://monitoring.pitchai.test",
    )


@pytest.mark.parametrize("dispatch_base_url", ["", "https://dispatch.pitchai.net/"])
@pytest.mark.asyncio
async def test_unavailable_dispatch_endpoint_never_receives_request(
    tmp_path: Path,
    dispatch_base_url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = _settings(tmp_path, dispatch_base_url=dispatch_base_url)

    def reject_request(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"unexpected Dispatcher request: {request.method} {request.url}")

    caplog.set_level(logging.WARNING, logger="e2e-registry")
    async with httpx.AsyncClient(transport=httpx.MockTransport(reject_request)) as client:
        await maybe_dispatch_failure_investigation(
            http_client=client,
            settings=settings,
            prompt="read-only diagnosis",
        )

    assert "Dispatcher endpoint unavailable; skipping dispatch" in caplog.text


@pytest.mark.asyncio
async def test_runner_completion_remains_successful_when_dispatch_is_sso_redirected(
    tmp_path: Path,
    sso_redirect_base_url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="e2e-registry")
    settings = _settings(tmp_path, dispatch_base_url=sso_redirect_base_url)
    tenant = dbm.create_tenant(settings, name="AFASAsk monitoring")
    test = dbm.insert_test(
        settings,
        tenant_id=str(tenant["id"]),
        name="afasask_demo_codex_fast_ok",
        base_url="https://demo.afasask.nl",
        test_kind="playwright_python",
        interval_seconds=300,
        timeout_seconds=60,
        jitter_seconds=0,
        down_after_failures=1,
        up_after_successes=1,
        notify_on_recovery=True,
        dispatch_on_failure=True,
    )
    claimed = dbm.claim_due_runs(settings, max_runs=1)
    assert len(claimed) == 1
    assert claimed[0].test_id == test["id"]

    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://registry.test") as client:
        response = await client.post(
            f"/api/v1/runner/runs/{claimed[0].run_id}/complete",
            headers={"Authorization": f"Bearer {settings.runner_token}"},
            json={
                "status": "fail",
                "elapsed_ms": 8123,
                "error_kind": "agent_error",
                "error_message": "AFASAsk response failed",
                "final_url": "https://demo.afasask.nl/chat/demo/monitor-check",
                "artifacts": {"failure_screenshot": "failure.png"},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["outcome"]["updated"] is True
    assert payload["outcome"]["alerted_down"] is True

    summary = dbm.status_summary(settings)
    assert summary["failing_tests"] == 1
    records = dbm.list_dispatch_runs(settings)
    assert len(records) == 1
    assert records[0]["queue_state"] == "dispatch_error"
    assert records[0]["bundle"] is None
    assert records[0]["context"]["test_id"] == test["id"]
    assert records[0]["context"]["run_id"] == claimed[0].run_id
    assert "302" in records[0]["error_message"]
    assert "dispatch-token-in-url" not in records[0]["error_message"]
    assert "<redacted>" in records[0]["error_message"]
    assert "dispatch-token-in-url" not in caplog.text
    assert "<redacted>" in caplog.text
