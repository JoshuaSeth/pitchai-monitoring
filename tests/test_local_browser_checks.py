# Copyright (c) 2026 PitchAI. All rights reserved.
"""Browser-backed checks against the deterministic local test server."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest

from domain_checks.common_check import DomainCheckSpec, SelectorCheck, browser_check
from domain_checks.testing import verify
from tests.local_server_support import launched_browser, numeric_detail, serve_local_http, string_list_detail

if TYPE_CHECKING:
    from collections.abc import Iterator

MAX_SHARED_SELECTOR_SECONDS = 3.0


@pytest.fixture(scope="module", name="local_server_base_url")
def local_server_fixture() -> Iterator[str]:
    """Run the deterministic local HTTP server for this test module.

    Yields:
        The local server's base URL.
    """
    with serve_local_http() as base_url:
        yield base_url


@pytest.mark.asyncio
async def test_browser_check_ok(local_server_base_url: str) -> None:
    """Verify a healthy page passes all configured browser assertions."""
    spec = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/ok",
        expected_title_contains="OK Page",
        required_selectors_all=[SelectorCheck(selector="nav", state="visible")],
        browser_timeout_seconds=5.0,
    )
    async with launched_browser() as browser:
        ok, details = await browser_check(spec, browser)

    verify(ok is True)
    verify(details["title_ok"] is True)
    verify(details["missing_selectors_all"] == [])
    verify(numeric_detail(details, "browser_elapsed_ms") >= 0)


@pytest.mark.asyncio
async def test_browser_check_expected_final_host_suffix_enforced(local_server_base_url: str) -> None:
    """Verify the browser check enforces the configured final host suffix."""
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
    async with launched_browser() as browser:
        ok, details = await browser_check(spec_ok, browser)
        verify(ok is True)
        verify(details["final_host"] == "127.0.0.1")
        verify(details["final_host_ok"] is True)

        ok, details = await browser_check(spec_bad, browser)
        verify(ok is False)
        verify(details["final_host"] == "127.0.0.1")
        verify(details["final_host_ok"] is False)


@pytest.mark.asyncio
async def test_browser_check_title_mismatch_fails(local_server_base_url: str) -> None:
    """Verify an unexpected document title fails the browser check."""
    spec = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/ok",
        expected_title_contains="Some Other Title",
        browser_timeout_seconds=5.0,
    )
    async with launched_browser() as browser:
        ok, details = await browser_check(spec, browser)

    verify(ok is False)
    verify(details["title_ok"] is False)


@pytest.mark.asyncio
async def test_browser_check_required_any_selector(local_server_base_url: str) -> None:
    """Verify one matching selector satisfies the any-selector policy."""
    spec = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/ok",
        required_selectors_any=[
            SelectorCheck(selector="#does-not-exist", state="attached"),
            SelectorCheck(selector="nav", state="visible"),
        ],
        browser_timeout_seconds=5.0,
    )
    async with launched_browser() as browser:
        ok, details = await browser_check(spec, browser)

    verify(ok is True)
    verify(details["required_any_ok"] is True)


@pytest.mark.asyncio
async def test_browser_check_required_any_missing_fails(local_server_base_url: str) -> None:
    """Verify entirely missing any-selectors fail the browser check."""
    spec = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/ok",
        required_selectors_any=[
            SelectorCheck(selector="#does-not-exist", state="attached"),
            SelectorCheck(selector="#also-missing", state="attached"),
        ],
        browser_timeout_seconds=5.0,
    )
    async with launched_browser() as browser:
        ok, details = await browser_check(spec, browser)

    verify(ok is False)
    verify(details["required_any_ok"] is False)


@pytest.mark.asyncio
async def test_browser_check_required_any_timeout_not_multiplied(local_server_base_url: str) -> None:
    """Verify any-selector checks share one timeout budget."""
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
    async with launched_browser() as browser:
        started = time.monotonic()
        ok, details = await browser_check(spec, browser)
        elapsed = time.monotonic() - started

    verify(ok is False)
    verify(details["required_any_ok"] is False)
    verify(elapsed < MAX_SHARED_SELECTOR_SECONDS)


@pytest.mark.asyncio
async def test_browser_check_maintenance_fails(local_server_base_url: str) -> None:
    """Verify visible maintenance text fails the browser check."""
    spec = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/maintenance",
        browser_timeout_seconds=5.0,
    )
    async with launched_browser() as browser:
        ok, details = await browser_check(spec, browser)

    verify(ok is False)
    forbidden_hits = string_list_detail(details, "forbidden_hits")
    maintenance_hits = ["maintenance" in hit for hit in forbidden_hits]
    verify(any(maintenance_hits))
    verify(numeric_detail(details, "browser_elapsed_ms") >= 0)


@pytest.mark.asyncio
async def test_browser_check_missing_selector_fails(local_server_base_url: str) -> None:
    """Verify a required missing selector fails the browser check."""
    spec = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/missing_nav",
        required_selectors_all=[SelectorCheck(selector="nav", state="visible")],
        browser_timeout_seconds=5.0,
    )
    async with launched_browser() as browser:
        ok, details = await browser_check(spec, browser)

    verify(ok is False)
    verify("nav" in string_list_detail(details, "missing_selectors_all"))


@pytest.mark.asyncio
async def test_browser_check_does_not_raise_if_browser_closes_mid_check(local_server_base_url: str) -> None:
    """Verify a mid-check browser close returns an infrastructure failure."""
    spec = DomainCheckSpec(
        domain="local",
        url=f"{local_server_base_url}/ok",
        required_selectors_all=[SelectorCheck(selector="#definitely-missing", state="attached")],
        browser_timeout_seconds=10.0,
    )
    async with launched_browser() as browser:
        task = asyncio.create_task(browser_check(spec, browser))
        await asyncio.sleep(0.2)
        await browser.close()
        ok, details = await task

    verify(ok is False)
    verify(details.get("browser_infra_error") is True)
