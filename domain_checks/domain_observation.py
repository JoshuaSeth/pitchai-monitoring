# Copyright (c) 2026 PitchAI. All rights reserved.
"""HTTP and browser observations retain independent product/infrastructure results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .common_check import DomainCheckResult

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Awaitable, Callable

    from httpx import AsyncClient

    from .common_check import DomainCheckSpec
    from .event_bus_delivery import JsonObject


@dataclass(frozen=True)
class DomainProbes[BrowserT]:
    """The cycle's current callables and their structured result contract."""

    http: Callable[[DomainCheckSpec, AsyncClient], Awaitable[tuple[bool, JsonObject]]]
    browser: Callable[[DomainCheckSpec, BrowserT], Awaitable[tuple[bool, JsonObject]]]


async def observe_domain[BrowserT](
    spec: DomainCheckSpec,
    http_client: AsyncClient,
    browser: BrowserT | None,
    *,
    browser_semaphore: asyncio.Semaphore,
    probes: DomainProbes[BrowserT],
) -> DomainCheckResult:
    """Check HTTP first, then observe browser health under the existing semaphore.

    Returns:
        The product result with browser infrastructure degradation distinguished.
    """
    http_ok, http_details = await probes.http(spec, http_client)
    if not http_ok:
        return DomainCheckResult(domain=spec.domain, ok=False, reason="http_check_failed", details=http_details)
    if not spec.browser_enabled:
        return DomainCheckResult(domain=spec.domain, ok=True, reason="browser_not_applicable", details={
            **http_details, "browser_skipped": True,
            "browser_skip_reason": "explicit_http_contract", "browser_elapsed_ms": None,
        })
    if browser is None:
        return DomainCheckResult(domain=spec.domain, ok=True, reason="browser_degraded", details={
            **http_details, "error": "browser_unavailable", "browser_connected": False,
            "browser_infra_error": True, "browser_elapsed_ms": None,
        })
    async with browser_semaphore:
        browser_ok, browser_details = await probes.browser(spec, browser)
    details = {**http_details, **browser_details}
    if browser_ok:
        return DomainCheckResult(domain=spec.domain, ok=True, reason="ok", details=details)
    infrastructure = bool(browser_details.get("browser_infra_error"))
    reason = "browser_degraded" if infrastructure else "browser_check_failed"
    return DomainCheckResult(domain=spec.domain, ok=infrastructure, reason=reason, details=details)
