from __future__ import annotations

import asyncio

import httpx
import pytest

import domain_checks.main as monitor
from domain_checks.common_check import DomainCheckSpec


@pytest.mark.asyncio
async def test_check_one_domain_browser_unavailable_is_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_http_get_check(spec: DomainCheckSpec, client: httpx.AsyncClient):
        return True, {"status_code": 200, "http_elapsed_ms": 1.0}

    monkeypatch.setattr(monitor, "http_get_check", fake_http_get_check)

    spec = DomainCheckSpec(domain="example.com", url="https://example.com")
    async with httpx.AsyncClient() as http_client:
        result = await monitor.check_one_domain(
            spec,
            http_client,
            None,
            browser_semaphore=asyncio.Semaphore(1),
        )

    assert result.ok is True
    assert result.reason == "browser_degraded"
    assert result.details.get("error") == "browser_unavailable"
    assert result.details.get("browser_infra_error") is True

