# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tests for test api contract and synthetic behavior."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import pytest

from domain_checks.metrics_api_contract import run_api_contract_checks
from domain_checks.metrics_synthetic import run_synthetic_transactions
from domain_checks.testing import verify
from tests.local_server_support import launched_browser

pytest_plugins = ("tests.api_contract_support",)

if TYPE_CHECKING:
    from domain_checks.types import JsonObject


@pytest.mark.asyncio
async def test_api_contract_checks_ok_and_fail(local_server_base_url: str) -> None:
    """Verify api contract checks ok and fail."""
    checks_ok: list[JsonObject] = [
        {
            "name": "health",
            "path": "/health",
            "expected_status_codes": [200],
            "expected_content_type_contains": "application/json",
            "json_paths_required": ["status", "timestamp", "runtime_config_version"],
            "json_paths_equal": {"status": "healthy"},
        },
    ]

    checks_bad: list[JsonObject] = [
        {
            "name": "health_bad",
            "path": "/health_bad",
            "expected_status_codes": [200],
            "expected_content_type_contains": "application/json",
            "json_paths_required": ["timestamp"],
        },
    ]

    async with httpx.AsyncClient() as client:
        ok_res = await run_api_contract_checks(
            http_client=client,
            domain="svc",
            base_url=local_server_base_url,
            checks=checks_ok,
            timeout_seconds=2.0,
        )
        verify(ok_res)
        verify(ok_res[0].ok is True)

        bad_res = await run_api_contract_checks(
            http_client=client,
            domain="svc",
            base_url=local_server_base_url,
            checks=checks_bad,
            timeout_seconds=2.0,
        )
        verify(bad_res)
        verify(bad_res[0].ok is False)
        verify(
            bad_res[0].error in {"missing_json_paths", "json_value_mismatch"}
            or (bad_res[0].error or "").startswith("missing_json_paths"),
        )


@pytest.mark.asyncio
async def test_api_contract_root_path_is_not_nested_under_page_url(
    local_server_base_url: str,
) -> None:
    """Verify api contract root path is not nested under page url."""
    async with httpx.AsyncClient() as client:
        result = await run_api_contract_checks(
            http_client=client,
            domain="svc",
            base_url=f"{local_server_base_url}/page?mode=demo",
            checks=[
                {
                    "name": "health",
                    "path": "/health",
                    "json_paths_equal": {"status": "healthy"},
                },
            ],
            timeout_seconds=2.0,
        )

    verify(result)
    verify(result[0].ok is True)
    verify(result[0].url == f"{local_server_base_url}/health")


@pytest.mark.asyncio
async def test_api_contract_can_explicitly_skip_content_type_validation(
    local_server_base_url: str,
) -> None:
    """Verify api contract can explicitly skip content type validation."""
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
                },
            ],
            timeout_seconds=2.0,
        )

    verify(result)
    verify(result[0].ok is True)


@pytest.mark.asyncio
async def test_api_contract_substitutes_header_env_without_logging_secret(
    local_server_base_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify api contract substitutes header env without logging secret."""
    monkeypatch.setenv("PRIVATE_MONITOR_TOKEN", "secret-token")
    checks: list[JsonObject] = [
        {
            "name": "private",
            "path": "/private",
            "headers": {"Authorization": "Bearer ${PRIVATE_MONITOR_TOKEN}"},
            "expected_status_codes": [200],
            "json_paths_equal": {"status": "ok"},
        },
    ]

    async with httpx.AsyncClient() as client:
        res = await run_api_contract_checks(
            http_client=client,
            domain="svc",
            base_url=local_server_base_url,
            checks=checks,
            timeout_seconds=2.0,
        )

    verify(res)
    verify(res[0].ok is True)
    verify("secret-token" not in json.dumps(res[0].details))


@pytest.mark.asyncio
async def test_api_contract_missing_header_env_fails_without_secret_value(
    local_server_base_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify api contract missing header env fails without secret value."""
    monkeypatch.delenv("MISSING_MONITOR_TOKEN", raising=False)
    checks: list[JsonObject] = [
        {
            "name": "private",
            "path": "/private",
            "headers": {"Authorization": "Bearer ${MISSING_MONITOR_TOKEN}"},
            "expected_status_codes": [200],
            "json_paths_equal": {"status": "ok"},
        },
    ]

    async with httpx.AsyncClient() as client:
        res = await run_api_contract_checks(
            http_client=client,
            domain="svc",
            base_url=local_server_base_url,
            checks=checks,
            timeout_seconds=2.0,
        )

    verify(res)
    verify(res[0].ok is False)
    verify("missing_env_secrets" in (res[0].error or ""))
    verify("Bearer" not in json.dumps(res[0].details))


@pytest.mark.asyncio
async def test_synthetic_transactions_basic_flow(local_server_base_url: str) -> None:
    """Verify synthetic transactions basic flow."""
    async with launched_browser() as browser:
        tx: list[JsonObject] = [
            {
                "name": "click_next",
                "steps": [
                    {"type": "goto", "url": f"{local_server_base_url}/page"},
                    {"type": "click", "selector": "#go"},
                    {"type": "expect_url_contains", "value": "/next"},
                ],
            },
        ]
        res = await run_synthetic_transactions(
            domain="svc",
            base_url=local_server_base_url,
            browser=browser,
            transactions=tx,
            timeout_seconds=5.0,
        )
        verify(res)
        verify(res[0].ok is True)
