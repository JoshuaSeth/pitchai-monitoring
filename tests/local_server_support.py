# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared local HTTP and browser support for domain-check tests."""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING, override

import pytest
from playwright.async_api import async_playwright

from domain_checks.common_check import find_chromium_executable
from tests.http_server_support import HttpVerbHandlerMixin, running_http_server

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator, Mapping

    from playwright.async_api import Browser

    from domain_checks.types import JsonValue


class _Handler(HttpVerbHandlerMixin, BaseHTTPRequestHandler):
    """Serve deterministic pages used by HTTP and browser checks."""

    @override
    def handle_get(self) -> None:
        """Serve one deterministic test route."""
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
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        _ = self.wfile.write(body_bytes)

    @override
    def handle_post(self) -> None:
        """Reject unsupported POST requests explicitly."""
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)


@contextmanager
def serve_local_http() -> Generator[str]:
    """Serve deterministic pages on an ephemeral local port.

    Yields:
        The base URL for the running HTTP server.
    """
    with running_http_server(_Handler) as base_url:
        yield base_url


@asynccontextmanager
async def launched_browser() -> AsyncGenerator[Browser]:
    """Launch a fresh Chromium instance or skip when Chromium is unavailable.

    Yields:
        A fresh Playwright browser instance.
    """
    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            yield browser
        finally:
            if browser.is_connected():
                await browser.close()


def numeric_detail(details: Mapping[str, JsonValue], key: str) -> float:
    """Return a numeric check detail or fail with a precise assertion."""
    value = details.get(key)
    if not isinstance(value, (int, float)):
        pytest.fail(f"Expected numeric detail {key!r}, got {value!r}")
    return float(value)


def string_list_detail(details: Mapping[str, JsonValue], key: str) -> list[str]:
    """Return a string-list check detail or fail with a precise assertion."""
    value = details.get(key)
    if not isinstance(value, list):
        pytest.fail(f"Expected list detail {key!r}, got {value!r}")
    strings: list[str] = []
    for item in value:
        if not isinstance(item, str):
            pytest.fail(f"Expected string in detail {key!r}, got {item!r}")
        strings.append(item)
    return strings
