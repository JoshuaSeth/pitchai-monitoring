# Copyright (c) 2026 PitchAI. All rights reserved.
"""Browser-unavailable behavior at the stable main-module boundary."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx
import pytest

import domain_checks.main as monitor
from domain_checks.common_check import DomainCheckSpec
from domain_checks.testing import verify

if TYPE_CHECKING:
    from domain_checks.types import JsonObject


@pytest.mark.asyncio
async def test_check_one_domain_browser_unavailable_is_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify HTTP success remains healthy when the browser is unavailable."""
    async def fake_http_get_check(
        spec: DomainCheckSpec,
        client: httpx.AsyncClient,
    ) -> tuple[bool, JsonObject]:
        _ = spec
        _ = client
        await asyncio.sleep(0)
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

    verify(result.ok is True)
    verify(result.reason == "browser_degraded")
    verify(result.details.get("error") == "browser_unavailable")
    verify(result.details.get("browser_infra_error") is True)
