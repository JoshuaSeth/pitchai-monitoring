from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from domain_checks.dispatch_client import DispatchConfig, dispatch_job, get_last_agent_message, parse_dispatch_response, wait_for_terminal_status


@pytest.mark.parametrize(
    ("text", "bundle", "runner"),
    [
        ("queued:20250101_abcdef:runner:already_running", "20250101_abcdef", "already_running"),
        (" queued:bundle123:runner:mycontainer \n", "bundle123", "mycontainer"),
        ("queued:bundle123:runner:error:oops:details", "bundle123", "error:oops:details"),
    ],
)
def test_parse_dispatch_response(text: str, bundle: str, runner: str) -> None:
    got_bundle, got_runner = parse_dispatch_response(text)
    assert got_bundle == bundle
    assert got_runner == runner


class _FakeDispatchHandler(BaseHTTPRequestHandler):
    token = "token"
    bundle = "bundle123"
    status_calls = 0

    log_text = (
        "[prompt] Using queued bundle: /mnt/elise/prompts/queue/bundle123\n"
        '{"type":"thread.started","thread_id":"t-1"}\n'
        '{"type":"item.completed","item":{"type":"agent_message","text":"Investigated. Root cause: test."}}\n'
        '{"type":"response.completed"}\n'
    )

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _auth_ok(self) -> bool:
        return (self.headers.get("X-PitchAI-Dispatch-Token") or "") == self.token

    def _send_json(self, status: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/dispatch":
            self.send_error(404)
            return
        if not self._auth_ok():
            self.send_error(401)
            return
        n = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(n) if n > 0 else b"{}"
        payload = json.loads(raw.decode("utf-8"))
        assert "prompt" in payload
        assert "config_toml" in payload
        body = f"queued:{self.bundle}:runner:already_running".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if not self._auth_ok():
            self.send_error(401)
            return

        parsed = urlparse(self.path)
        if parsed.path == f"/runs/{self.bundle}/status":
            type(self).status_calls += 1
            queue_state = "processing" if type(self).status_calls < 2 else "processed"
            self._send_json(
                200,
                {
                    "queue_state": queue_state,
                    "runner_status": "running",
                    "thread_id": "t-1",
                    "live_status": None,
                    "record": {"bundle": self.bundle, "status": queue_state},
                },
            )
            return

        if parsed.path == f"/runs/{self.bundle}/log":
            qs = parse_qs(parsed.query)
            offset = int((qs.get("offset") or ["0"])[0])
            max_bytes = int((qs.get("max_bytes") or ["20000"])[0])
            raw = type(self).log_text.encode("utf-8")
            size = len(raw)
            offset = max(0, min(offset, size))
            max_bytes = max(1, min(max_bytes, 5_000_000))
            chunk = raw[offset : offset + max_bytes]
            next_offset = offset + len(chunk)
            self._send_json(
                200,
                {
                    "exists": True,
                    "offset": offset,
                    "next_offset": next_offset,
                    "size": size,
                    "eof": next_offset >= size,
                    "content": chunk.decode("utf-8", errors="replace"),
                },
            )
            return

        self.send_error(404)


@pytest.fixture(scope="module")
def fake_dispatcher_base_url() -> str:
    httpd = HTTPServer(("127.0.0.1", 0), _FakeDispatchHandler)
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
async def test_dispatch_end_to_end(fake_dispatcher_base_url: str) -> None:
    cfg = DispatchConfig(
        base_url=fake_dispatcher_base_url,
        token="token",
        poll_interval_seconds=0.01,
        max_wait_seconds=2.0,
        log_tail_bytes=50_000,
    )
    async with httpx.AsyncClient() as client:
        bundle, _runner = await dispatch_job(client, cfg, prompt="hi", config_toml="approval_policy='never'")
        assert bundle == "bundle123"
        status = await wait_for_terminal_status(client, cfg, bundle=bundle)
        assert status["queue_state"] == "processed"
        msg = await get_last_agent_message(client, cfg, bundle=bundle)
        assert msg == "Investigated. Root cause: test."


class _FlakyDispatchHandler(_FakeDispatchHandler):
    status_calls = 0

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == f"/runs/{self.bundle}/status":
            type(self).status_calls += 1
            if type(self).status_calls == 1:
                self.send_error(502)
                return
        super().do_GET()


@pytest.fixture(scope="module")
def flaky_dispatcher_base_url() -> str:
    _FlakyDispatchHandler.status_calls = 0
    httpd = HTTPServer(("127.0.0.1", 0), _FlakyDispatchHandler)
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
async def test_dispatch_polling_tolerates_transient_502(flaky_dispatcher_base_url: str) -> None:
    cfg = DispatchConfig(
        base_url=flaky_dispatcher_base_url,
        token="token",
        poll_interval_seconds=0.01,
        max_wait_seconds=2.0,
        log_tail_bytes=50_000,
    )
    async with httpx.AsyncClient() as client:
        bundle, _runner = await dispatch_job(client, cfg, prompt="hi", config_toml="approval_policy='never'")
        status = await wait_for_terminal_status(client, cfg, bundle=bundle)
        assert status["queue_state"] == "processed"
