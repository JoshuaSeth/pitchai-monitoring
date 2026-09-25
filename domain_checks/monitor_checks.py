# Copyright (c) 2026 PitchAI. All rights reserved.
"""One-domain monitor execution with explicit HTTP and browser dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from domain_checks.common_check import DomainCheckResult

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Awaitable, Callable

    import httpx
    from playwright.async_api import Browser

    from domain_checks.common_check import DomainCheckSpec
    from domain_checks.types import JsonObject

    HttpCheck = Callable[[DomainCheckSpec, httpx.AsyncClient], Awaitable[tuple[bool, JsonObject]]]
    BrowserCheck = Callable[[DomainCheckSpec, Browser], Awaitable[tuple[bool, JsonObject]]]


@dataclass(frozen=True)
class CheckDependencies:
    """HTTP and browser implementations used for one domain check."""

    http_check: HttpCheck
    browser_check: BrowserCheck


async def check_one_domain(
    spec: DomainCheckSpec,
    http_client: httpx.AsyncClient,
    browser: Browser | None,
    *,
    browser_semaphore: asyncio.Semaphore,
    dependencies: CheckDependencies,
) -> DomainCheckResult:
    """Evaluate HTTP first and then the optional browser contract.

    Returns:
        The normalized domain check result.
    """
    http_ok, http_details = await dependencies.http_check(spec, http_client)
    if not http_ok:
        return DomainCheckResult(
            domain=spec.domain,
            ok=False,
            reason="http_check_failed",
            details=http_details,
        )
    if not spec.browser_enabled:
        return DomainCheckResult(
            domain=spec.domain,
            ok=True,
            reason="browser_not_applicable",
            details={
                **http_details,
                "browser_skipped": True,
                "browser_skip_reason": "explicit_http_contract",
                "browser_elapsed_ms": None,
            },
        )
    if browser is None:
        return DomainCheckResult(
            domain=spec.domain,
            ok=True,
            reason="browser_degraded",
            details={
                **http_details,
                "error": "browser_unavailable",
                "browser_connected": False,
                "browser_infra_error": True,
                "browser_elapsed_ms": None,
            },
        )
    async with browser_semaphore:
        browser_ok, browser_details = await dependencies.browser_check(spec, browser)
    details = {**http_details, **browser_details}
    if browser_ok:
        return DomainCheckResult(domain=spec.domain, ok=True, reason="ok", details=details)
    if bool(browser_details.get("browser_infra_error")):
        return DomainCheckResult(domain=spec.domain, ok=True, reason="browser_degraded", details=details)
    return DomainCheckResult(domain=spec.domain, ok=False, reason="browser_check_failed", details=details)
