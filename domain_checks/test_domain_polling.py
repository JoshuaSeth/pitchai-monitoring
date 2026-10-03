# Copyright (c) 2026 PitchAI. All rights reserved.
"""Native async ownership tests without HTTP, browsers or outgoing dispatch."""

from __future__ import annotations

import asyncio
import unittest
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from .browser_admission import BrowserAdmission
from .common_check import DomainCheckResult, DomainCheckSpec
from .cycle_channels import CycleChannels
from .dft_test_support import require
from .dispatch_records import DispatchRecords
from .domain_polling import DomainPolling
from .telegram import TelegramConfig

if TYPE_CHECKING:
    from httpx import AsyncClient

    from .browser_admission import BrowserConnection
    from .domain_polling import DomainCheckCall


def _poller(check: AsyncMock) -> DomainPolling[BrowserConnection]:
    browser = cast("BrowserConnection", MagicMock())
    admission: BrowserAdmission[BrowserConnection] = BrowserAdmission({}, AsyncMock(), dict, browser)
    return DomainPolling(asyncio.Semaphore(1), asyncio.Semaphore(1), cast("AsyncClient", MagicMock()), admission, check)


class TestDomainPolling(unittest.IsolatedAsyncioTestCase):
    """The real domain semaphore governs attempt and browser sampling order."""

    @staticmethod
    async def test_browser_sampled_after_semaphore_admission() -> None:
        """A browser replacement during queued admission reaches the eventual probe."""
        result = DomainCheckResult(domain="fixture.invalid", ok=True, reason="fixture", details={})
        check = AsyncMock(return_value=result)
        poller = _poller(check)
        await poller.semaphore.acquire()
        spec = DomainCheckSpec("fixture.invalid", "https://fixture.invalid")
        task = asyncio.create_task(poller.run(spec))
        await asyncio.sleep(0)
        check.assert_not_awaited()
        replacement = cast("BrowserConnection", MagicMock())
        poller.admission.browser = replacement
        poller.semaphore.release()
        require(condition=await task is result, message="result identity changed")
        check.assert_awaited_once_with({"spec": spec, "http_client": poller.client,
                                       "browser": replacement, "browser_semaphore": poller.browser_semaphore})
        require(condition=not poller.semaphore.locked(), message="completed check leaked domain permit")

    @staticmethod
    async def test_check_failure_releases_admission() -> None:
        """The original check-crash result remains distinct from a successful observation."""
        poller = _poller(AsyncMock(side_effect=ValueError("synthetic")))
        log = MagicMock()
        with patch("domain_checks.domain_polling.LOGGER.error", new=log):
            result = await poller.run(DomainCheckSpec("fixture.invalid", "https://fixture.invalid"))
        require(condition=not result.ok and result.reason == "check_crashed"
                and result.details == {"error": "ValueError: synthetic"}, message="check crash diagnostic changed")
        require(condition=not poller.semaphore.locked(), message="failed check leaked domain permit")
        log.assert_called_once()

    @staticmethod
    async def test_probe_cancellation_retains_browser_and_releases_admission() -> None:
        """Cancelling an in-flight observation neither fabricates a result nor closes its browser."""
        started = asyncio.Event()
        hold = asyncio.Event()

        async def check(_inputs: DomainCheckCall[BrowserConnection]) -> DomainCheckResult:
            started.set()
            await hold.wait()
            return DomainCheckResult(domain="fixture.invalid", ok=True, reason="unreachable", details={})

        poller = _poller(AsyncMock(side_effect=check))
        browser = poller.admission.browser
        task = asyncio.create_task(poller.run(DomainCheckSpec("fixture.invalid", "https://fixture.invalid")))
        await started.wait()
        _ = task.cancel()
        result = await asyncio.gather(task, return_exceptions=True)
        require(condition=isinstance(result[0], asyncio.CancelledError), message="check cancellation suppressed")
        require(condition=poller.admission.browser is browser and not poller.semaphore.locked(),
                message="cancelled check changed browser ownership or leaked permit")


class TestDispatchCompletion(unittest.IsolatedAsyncioTestCase):
    """Observe actual completed/pending/cancelled tasks without invoking dispatch."""

    @staticmethod
    async def test_completed_errors_are_removed_pending_and_cancelled_retained() -> None:
        """Snapshot order stops at cancellation and leaves later tasks under cycle ownership."""
        ready = asyncio.Event()
        ready.set()
        pending = asyncio.Event()

        async def failing() -> None:
            await ready.wait()
            message = "synthetic dispatch failure"
            raise ValueError(message)

        async def waiting(event: asyncio.Event) -> None:
            await event.wait()

        success = asyncio.create_task(waiting(ready))
        failed = asyncio.create_task(failing())
        active = asyncio.create_task(waiting(pending))
        cancelled = asyncio.create_task(waiting(pending))
        later = asyncio.create_task(waiting(ready))
        _ = await asyncio.gather(success, failed, later, return_exceptions=True)
        _ = cancelled.cancel()
        _ = await asyncio.gather(cancelled, return_exceptions=True)
        tasks = {"success": success, "failed": failed, "active": active, "cancelled": cancelled, "later": later}
        channels = CycleChannels(cast("AsyncClient", MagicMock()), TelegramConfig("synthetic", "synthetic"),
                                 None, {}, DispatchRecords(), tasks)

        async def prune() -> None:
            await ready.wait()
            channels.prune_completed()

        log = MagicMock()
        with patch("domain_checks.cycle_channels.LOGGER.error", new=log):
            outcome = await asyncio.gather(prune(), return_exceptions=True)
        require(condition=isinstance(outcome[0], asyncio.CancelledError), message="cancelled dispatch result swallowed")
        require(condition=list(tasks) == ["active", "cancelled", "later"], message="dispatch ownership/order changed")
        log.assert_called_once()
        pending.set()
        await active
