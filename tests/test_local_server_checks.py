# Copyright (c) 2026 PitchAI. All rights reserved.
"""HTTP checks against the deterministic local test server."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import httpx
import pytest

from domain_checks.common_check import DomainCheckSpec, http_get_check
from domain_checks.testing import verify
from tests.local_server_support import numeric_detail, serve_local_http, string_list_detail

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(scope="module", name="local_server_base_url")
def local_server_fixture() -> Iterator[str]:
    """Run the deterministic local HTTP server for this test module.

    Yields:
        The local server's base URL.
    """
    with serve_local_http() as base_url:
        yield base_url


@pytest.mark.asyncio
async def test_http_get_ok(local_server_base_url: str) -> None:
    """Verify a healthy response passes the HTTP check."""
    spec = DomainCheckSpec(domain="local", url=f"{local_server_base_url}/ok", http_timeout_seconds=5.0)
    async with httpx.AsyncClient() as client:
        ok, details = await http_get_check(spec, client)
    verify(ok is True)
    verify(details["status_code"] == HTTPStatus.OK)
    verify(details["forbidden_hits"] == [])
    verify(numeric_detail(details, "http_elapsed_ms") >= 0)


@pytest.mark.asyncio
async def test_http_get_redirect_is_ok(local_server_base_url: str) -> None:
    """Verify redirect following preserves a healthy HTTP result."""
    spec = DomainCheckSpec(domain="local", url=f"{local_server_base_url}/redirect", http_timeout_seconds=5.0)
    async with httpx.AsyncClient() as client:
        ok, details = await http_get_check(spec, client)
    verify(ok is True)
    verify(details["status_code"] == HTTPStatus.OK)
    verify(str(details["final_url"]).endswith("/ok"))
    verify(numeric_detail(details, "http_elapsed_ms") >= 0)


@pytest.mark.asyncio
async def test_http_get_expected_final_host_suffix_enforced(local_server_base_url: str) -> None:
    """Verify the HTTP check enforces the configured final host suffix."""
    async with httpx.AsyncClient() as client:
        spec_ok = DomainCheckSpec(
            domain="local",
            url=f"{local_server_base_url}/ok",
            http_timeout_seconds=5.0,
            expected_final_host_suffix="127.0.0.1",
        )
        ok, details = await http_get_check(spec_ok, client)
        verify(ok is True)
        verify(details["final_host"] == "127.0.0.1")
        verify(details["final_host_ok"] is True)

        spec_bad = DomainCheckSpec(
            domain="local",
            url=f"{local_server_base_url}/ok",
            http_timeout_seconds=5.0,
            expected_final_host_suffix="example.com",
        )
        ok, details = await http_get_check(spec_bad, client)
        verify(ok is False)
        verify(details["final_host"] == "127.0.0.1")
        verify(details["final_host_ok"] is False)


@pytest.mark.asyncio
async def test_http_get_maintenance_detected(local_server_base_url: str) -> None:
    """Verify visible maintenance text fails the HTTP check."""
    spec = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/maintenance",
        http_timeout_seconds=5.0,
    )
    async with httpx.AsyncClient() as client:
        ok, details = await http_get_check(spec, client)
    verify(ok is False)
    verify(details["status_code"] == HTTPStatus.OK)
    forbidden_hits = string_list_detail(details, "forbidden_hits")
    maintenance_hits = ["maintenance" in hit for hit in forbidden_hits]
    verify(any(maintenance_hits))
    verify(numeric_detail(details, "http_elapsed_ms") >= 0)


@pytest.mark.asyncio
async def test_http_get_ignores_script_text(local_server_base_url: str) -> None:
    """Verify forbidden text inside scripts does not fail the HTTP check."""
    spec = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/script_contains_forbidden",
        http_timeout_seconds=5.0,
    )
    async with httpx.AsyncClient() as client:
        ok, details = await http_get_check(spec, client)
    verify(ok is True)
    verify(details["status_code"] == HTTPStatus.OK)
    verify(details["forbidden_hits"] == [])
    verify(numeric_detail(details, "http_elapsed_ms") >= 0)


@pytest.mark.asyncio
async def test_http_get_bad_gateway_fails(local_server_base_url: str) -> None:
    """Verify a disallowed gateway error fails the HTTP check."""
    spec = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/bad_gateway",
        http_timeout_seconds=5.0,
    )
    async with httpx.AsyncClient() as client:
        ok, details = await http_get_check(spec, client)
    verify(ok is False)
    verify(details["status_code"] == HTTPStatus.BAD_GATEWAY)
    verify(numeric_detail(details, "http_elapsed_ms") >= 0)


@pytest.mark.asyncio
async def test_http_get_allows_explicit_status_codes(local_server_base_url: str) -> None:
    """Verify an explicitly allowed gateway status passes the HTTP check."""
    spec = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/bad_gateway",
        http_timeout_seconds=5.0,
        allowed_status_codes=[HTTPStatus.BAD_GATEWAY],
        forbidden_text_any=[],
    )
    async with httpx.AsyncClient() as client:
        ok, details = await http_get_check(spec, client)
    verify(ok is True)
    verify(details["status_code"] == HTTPStatus.BAD_GATEWAY)
    verify(numeric_detail(details, "http_elapsed_ms") >= 0)
