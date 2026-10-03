# Copyright (c) 2026 PitchAI. All rights reserved.
"""Concurrency and failure ownership for the existing per-domain check calls."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, TypedDict

from .common_check import DomainCheckResult

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Awaitable, Callable
    from types import TracebackType

    from httpx import AsyncClient

    from .browser_admission import BrowserAdmission, BrowserConnection
    from .common_check import DomainCheckSpec

LOGGER = logging.getLogger("service-monitoring")


class DomainCheckCall[BrowserT](TypedDict):
    """The existing native check signature, sampled only after acquiring admission."""

    spec: DomainCheckSpec
    http_client: AsyncClient
    browser: BrowserT | None
    browser_semaphore: asyncio.Semaphore


@dataclass
class DomainCheckBoundary:
    """Keep ordinary check failures distinct from product and cancellation results."""

    domain: str
    error: str = ""

    def __enter__(self) -> Self:
        """Return this single check boundary with an empty failure diagnostic."""
        self.error = ""
        return self

    def __exit__(self, _kind: type[BaseException] | None, error: BaseException | None,
                 traceback: TracebackType | None) -> bool:
        """Return true only after recording the original ordinary check-crash diagnostic."""
        if not isinstance(error, Exception):
            return False
        self.error = f"{type(error).__name__}: {error}"
        LOGGER.error("Domain check crashed domain=%s error=%s", self.domain, self.error,
                     exc_info=(type(error), error, traceback))
        return True


@dataclass(frozen=True)
class DomainPolling[BrowserT: BrowserConnection]:
    """Reuse the current semaphores and browser ownership without scheduling extra work."""

    semaphore: asyncio.Semaphore
    browser_semaphore: asyncio.Semaphore
    client: AsyncClient
    admission: BrowserAdmission[BrowserT]
    check: Callable[[DomainCheckCall[BrowserT]], Awaitable[DomainCheckResult]]

    async def run(self, spec: DomainCheckSpec) -> DomainCheckResult:
        """Observe the current browser after acquiring the existing domain semaphore.

        Returns:
            The original result object or the existing ordinary-crash sentinel.
        """
        async with self.semaphore:
            with DomainCheckBoundary(spec.domain) as boundary:
                return await self.check({"spec": spec, "http_client": self.client,
                                         "browser": self.admission.browser,
                                         "browser_semaphore": self.browser_semaphore})
            return DomainCheckResult(domain=spec.domain, ok=False, reason="check_crashed",
                                     details={"error": boundary.error})
