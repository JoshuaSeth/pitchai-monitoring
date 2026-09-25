# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tests for test dispatch client behavior."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING, cast, override
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from domain_checks.dispatch_client import (
    DispatchConfig,
    dispatch_job,
    extract_last_error_message_from_exec_log,
    get_last_agent_message,
    parse_dispatch_response,
    wait_for_terminal_status,
)
from domain_checks.testing import verify
from tests.http_server_support import HttpVerbHandlerMixin, running_http_server

if TYPE_CHECKING:
    from collections.abc import Iterator

    from domain_checks.types import JsonObject

_DISPATCH_AUTH_VALUE = "token"
_PROCESSED_STATUS_CALL = 2


@pytest.mark.parametrize(
    ("text", "bundle", "runner"),
    [
        ("queued:20250101_abcdef:runner:already_running", "20250101_abcdef", "already_running"),
        (" queued:bundle123:runner:mycontainer \n", "bundle123", "mycontainer"),
        ("queued:bundle123:runner:error:oops:details", "bundle123", "error:oops:details"),
    ],
)
def test_parse_dispatch_response(text: str, bundle: str, runner: str) -> None:
    """Verify parse dispatch response."""
    got_bundle, got_runner = parse_dispatch_response(text)
    verify(got_bundle == bundle)
    verify(got_runner == runner)


def test_extract_last_error_message_from_exec_log_prefers_latest() -> None:
    """Verify extract last error message from exec log prefers latest."""
    text = 'not json\n{"type":"error","message":"first"}\n{"type":"turn.failed","error":{"message":"second"}}\n'
    verify(extract_last_error_message_from_exec_log(text) == "second")


class _FakeDispatchHandler(HttpVerbHandlerMixin, BaseHTTPRequestHandler):
    dispatch_auth: str = _DISPATCH_AUTH_VALUE
    bundle: str = "bundle123"
    status_calls: int = 0

    log_text: str = (
        "[prompt] Using queued bundle: /mnt/elise/prompts/queue/bundle123\n"
        '{"type":"thread.started","thread_id":"t-1"}\n'
        '{"type":"item.completed","item":{"type":"agent_message","text":"Investigated. Root cause: test."}}\n'
        '{"type":"response.completed"}\n'
    )

    def _auth_ok(self) -> bool:
        return (self.headers.get("X-PitchAI-Dispatch-Token") or "") == self.dispatch_auth

    def _send_json(self, status: int, obj: JsonObject) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        _ = self.wfile.write(body)

    @override
    def handle_post(self) -> None:
        """Accept a deterministic dispatch request."""
        if self.path != "/dispatch":
            self.send_error(404)
            return
        if not self._auth_ok():
            self.send_error(401)
            return
        n = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(n) if n > 0 else b"{}"
        payload = cast("JsonObject", json.loads(raw.decode("utf-8")))
        verify("prompt" in payload)
        verify("config_toml" in payload)
        body = f"queued:{self.bundle}:runner:already_running".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        _ = self.wfile.write(body)

    @override
    def handle_get(self) -> None:
        """Serve deterministic status and log responses."""
        if not self._auth_ok():
            self.send_error(401)
            return

        parsed = urlparse(self.path)
        if parsed.path == f"/runs/{self.bundle}/status":
            type(self).status_calls += 1
            queue_state = "processing" if type(self).status_calls < _PROCESSED_STATUS_CALL else "processed"
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


@pytest.fixture(scope="module", name="fake_dispatcher_base_url")
def fake_dispatcher_fixture() -> Iterator[str]:
    """Run the fake dispatcher.

    Yields:
        The dispatcher base URL.
    """
    with running_http_server(_FakeDispatchHandler) as base_url:
        yield base_url


@pytest.mark.asyncio
async def test_dispatch_end_to_end(fake_dispatcher_base_url: str) -> None:
    """Verify dispatch end to end."""
    cfg = DispatchConfig(
        base_url=fake_dispatcher_base_url,
        token=_DISPATCH_AUTH_VALUE,
        poll_interval_seconds=0.01,
        max_wait_seconds=2.0,
        log_tail_bytes=50_000,
    )
    async with httpx.AsyncClient() as client:
        bundle, _runner = await dispatch_job(client, cfg, prompt="hi", config_toml="approval_policy='never'")
        verify(bundle == "bundle123")
        status = await wait_for_terminal_status(client, cfg, bundle=bundle)
        verify(status.get("queue_state") == "processed")
        msg = await get_last_agent_message(client, cfg, bundle=bundle)
        verify(msg == "Investigated. Root cause: test.")


class _FlakyDispatchHandler(_FakeDispatchHandler):
    status_calls: int = 0

    @override
    def handle_get(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == f"/runs/{self.bundle}/status":
            type(self).status_calls += 1
            if type(self).status_calls == 1:
                self.send_error(502)
                return
        super().handle_get()


@pytest.fixture(scope="module", name="flaky_dispatcher_base_url")
def flaky_dispatcher_fixture() -> Iterator[str]:
    """Run the flaky dispatcher.

    Yields:
        The dispatcher base URL.
    """
    _FlakyDispatchHandler.status_calls = 0
    with running_http_server(_FlakyDispatchHandler) as base_url:
        yield base_url


@pytest.mark.asyncio
async def test_dispatch_polling_tolerates_transient_502(flaky_dispatcher_base_url: str) -> None:
    """Verify dispatch polling tolerates transient 502."""
    cfg = DispatchConfig(
        base_url=flaky_dispatcher_base_url,
        token=_DISPATCH_AUTH_VALUE,
        poll_interval_seconds=0.01,
        max_wait_seconds=2.0,
        log_tail_bytes=50_000,
    )
    async with httpx.AsyncClient() as client:
        bundle, _runner = await dispatch_job(client, cfg, prompt="hi", config_toml="approval_policy='never'")
        status = await wait_for_terminal_status(client, cfg, bundle=bundle)
        verify(status.get("queue_state") == "processed")
