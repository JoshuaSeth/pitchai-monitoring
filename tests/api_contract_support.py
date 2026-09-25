# Copyright (c) 2026 PitchAI. All rights reserved.
"""Local HTTP fixture shared by API-contract and synthetic-check tests."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING, override

import pytest

from tests.http_server_support import HttpVerbHandlerMixin, running_http_server

if TYPE_CHECKING:
    from collections.abc import Iterator


class _Handler(HttpVerbHandlerMixin, BaseHTTPRequestHandler):
    def _send(self, status: int, headers: dict[str, str], body: bytes) -> None:
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        _ = self.wfile.write(body)

    @override
    def handle_get(self) -> None:
        """Serve deterministic API-contract and browser routes."""
        if self.path == "/private":
            expected = "Bearer secret-token"
            received = self.headers.get("Authorization") or ""
            if received != expected:
                body = json.dumps({"status": "unauthorized"}).encode()
                self._send(401, {"Content-Type": "application/json"}, body)
                return
            body = json.dumps({"status": "ok"}).encode()
            self._send(200, {"Content-Type": "application/json"}, body)
            return

        if self.path == "/health":
            payload = {
                "status": "healthy",
                "timestamp": "t-1",
                "runtime_config_version": "v1",
            }
            body = json.dumps(payload).encode()
            self._send(200, {"Content-Type": "application/json"}, body)
            return

        if self.path == "/health_bad":
            body = json.dumps({"status": "healthy"}).encode()
            self._send(200, {"Content-Type": "application/json"}, body)
            return

        if self.path == "/page":
            html = (
                "<!doctype html><html><head><title>Page</title></head>"
                '<body><a href="/next" id="go">Next</a></body></html>'
            )
            self._send(200, {"Content-Type": "text/html; charset=utf-8"}, html.encode())
            return

        if self.path == "/next":
            html = "<!doctype html><html><head><title>Next</title></head><body><h1>Next</h1></body></html>"
            self._send(200, {"Content-Type": "text/html; charset=utf-8"}, html.encode())
            return

        self._send(404, {"Content-Type": "text/plain; charset=utf-8"}, b"not found")

    @override
    def handle_post(self) -> None:
        """Reject unsupported POST requests explicitly."""
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)


@pytest.fixture(scope="module")
def local_server_base_url() -> Iterator[str]:
    """Run the local HTTP server.

    Yields:
        The server base URL.
    """
    with running_http_server(_Handler) as base_url:
        yield base_url
