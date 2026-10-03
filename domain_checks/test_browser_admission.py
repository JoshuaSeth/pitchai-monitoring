# Copyright (c) 2026 PitchAI. All rights reserved.
"""Browser lifecycle tests use synthetic handles and no native process."""

from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

from .browser_admission import BrowserAdmission
from .dft_test_support import require, require_error

if TYPE_CHECKING:
    from .browser_admission import BrowserStateValue


@dataclass
class SyntheticBrowser:
    """Count actual lifecycle calls and inject errors without a native handle."""

    connected: bool = True
    connection_error: Exception | None = None
    close_error: BaseException | None = None
    close_count: int = 0

    def is_connected(self) -> bool:
        """Return synthetic connectivity or propagate its configured error."""
        if self.connection_error is not None:
            raise self.connection_error
        return self.connected

    async def close(self) -> None:
        """Count cleanup before propagating its configured failure or cancellation."""
        self.close_count += 1
        if self.close_error is not None:
            raise self.close_error
        self.connected = False


class BrowserAdmissionTests(unittest.IsolatedAsyncioTestCase):
    """Reuse, failed launch and cancellation preserve exact ownership and retry state."""

    @staticmethod
    async def test_connected_browser_precedes_retry_and_memory_checks() -> None:
        """An existing connected handle is retained even with a future retry marker."""
        browser = SyntheticBrowser()
        launch, memory = AsyncMock(), MagicMock()
        state: dict[str, BrowserStateValue] = {"browser_launch_next_try_ts": 200, "browser_min_mem_available_mb": 2048}
        admission = BrowserAdmission[SyntheticBrowser](state, launch, memory, browser)
        result = await admission.ensure(100)
        require(condition=result is browser and admission.browser is browser, message="connected handle replaced")
        require(condition=launch.await_count == 0 and memory.call_count == 0, message="unneeded admission check")
        require(condition=browser.close_count == 0, message="connected browser closed")

    @staticmethod
    async def test_disconnected_cleanup_failure_still_allows_launch() -> None:
        """Independent connection and close exceptions do not disable HTTP monitoring."""
        old = SyntheticBrowser(connection_error=RuntimeError("synthetic disconnected"),
                               close_error=RuntimeError("synthetic close failed"))
        fresh = SyntheticBrowser()
        state: dict[str, BrowserStateValue] = {"browser_launch_fail_count": 4, "browser_launch_last_error": "old"}
        admission = BrowserAdmission[SyntheticBrowser](state, AsyncMock(return_value=fresh), MagicMock(), old)
        result = await admission.ensure(100)
        require(condition=result is fresh and admission.browser is fresh, message="replacement not retained")
        require(condition=old.close_count == 1 and state["browser_launch_fail_count"] == 0
                and state["browser_launch_last_error"] is None, message="success state not reset")

    @staticmethod
    async def test_retry_equality_admits_and_future_time_waits() -> None:
        """The equality boundary launches once; earlier observations do not renew delay."""
        launch = AsyncMock(return_value=SyntheticBrowser())
        state: dict[str, BrowserStateValue] = {"browser_launch_next_try_ts": 100}
        admission = BrowserAdmission[SyntheticBrowser](state, launch, MagicMock())
        require(condition=(await admission.ensure(99), state["browser_launch_next_try_ts"]) == (None, 100),
                message="retry wait changed")
        require(condition=launch.await_count == 0, message="launched before retry boundary")
        require(condition=await admission.ensure(100) is not None and launch.await_count == 1,
                message="equality did not launch")

    @staticmethod
    async def test_low_memory_wait_preserves_failure_count_and_exact_threshold() -> None:
        """Only known memory below the threshold delays by 60 seconds without a launch failure."""
        for available, admitted in ((2047, False), (2048, True), (2049, True)):
            launch = AsyncMock(return_value=SyntheticBrowser())
            state: dict[str, BrowserStateValue] = {"browser_min_mem_available_mb": 2, "browser_launch_fail_count": 3}
            memory = MagicMock(return_value={"MemAvailable": available})
            admission = BrowserAdmission[SyntheticBrowser](state, launch, memory)
            result = await admission.ensure(100)
            require(condition=(result is not None) is admitted, message="memory threshold changed")
            if not admitted:
                require(condition=(state["browser_launch_next_try_ts"], state["browser_launch_fail_count"]) == (160, 3),
                        message="low memory counted as failed launch")
                require(condition=state["browser_launch_last_error"] == "low_mem_available_mb=1 < 2",
                        message="memory diagnostic changed")

    @staticmethod
    async def test_missing_memory_allows_launch_and_read_failure_propagates() -> None:
        """Unavailable data is not fabricated as zero, and reader exceptions stay outside launch handling."""
        state: dict[str, BrowserStateValue] = {"browser_min_mem_available_mb": 2}
        launch = AsyncMock(return_value=SyntheticBrowser())
        admission = BrowserAdmission[SyntheticBrowser](state, launch, MagicMock(return_value={}))
        require(condition=await admission.ensure(100) is not None, message="missing memory denied launch")
        failure = RuntimeError("synthetic read failure")
        failing = BrowserAdmission[SyntheticBrowser](state, launch, MagicMock(side_effect=failure))
        with require_error(RuntimeError, "synthetic read failure"):
            await failing.ensure(200)
        require(condition=state["browser_launch_fail_count"] == 0, message="read failure changed launch counter")

    @staticmethod
    async def test_failed_launch_preserves_error_and_caps_backoff() -> None:
        """Consecutive failure counters retain exponential delay capped at 300 seconds."""
        for prior, delay in ((0, 10), (1, 20), (4, 160), (5, 300), (100, 300)):
            state: dict[str, BrowserStateValue] = {"browser_launch_fail_count": prior}
            launch = AsyncMock(side_effect=RuntimeError("synthetic"))
            admission = BrowserAdmission[SyntheticBrowser](state, launch, MagicMock())
            with patch("domain_checks.browser_launch_boundary.LOGGER.warning"):
                result = await admission.ensure(100)
            require(condition=result is None and admission.browser is None, message="failed launch retained handle")
            require(condition=state["browser_launch_fail_count"] == prior + 1
                    and state["browser_launch_next_try_ts"] == 100 + delay, message="backoff changed")
            require(condition=state["browser_launch_last_error"] == "RuntimeError: synthetic", message="error changed")

    @staticmethod
    async def test_cancelled_relaunch_does_not_retain_closed_handle_or_mark_failure() -> None:
        """Cancellation after disconnected cleanup keeps the cleared ownership and original state."""
        old = SyntheticBrowser(connected=False)
        state: dict[str, BrowserStateValue] = {"browser_launch_fail_count": 2}
        launch = AsyncMock(side_effect=asyncio.CancelledError("synthetic"))
        admission = BrowserAdmission[SyntheticBrowser](state, launch, MagicMock(), old)
        task = asyncio.create_task(admission.ensure(100))
        outcomes = await asyncio.gather(task, return_exceptions=True)
        require(condition=task.cancelled() and isinstance(outcomes[0], asyncio.CancelledError),
                message="launch cancellation was swallowed")
        require(condition=admission.browser is None and old.close_count == 1, message="closed handle retained")
        require(condition=state == {"browser_launch_fail_count": 2}, message="cancellation counted as launch failure")

    @staticmethod
    async def test_cancelled_close_preserves_handle_for_outer_cleanup() -> None:
        """Cancellation during close leaves ownership intact for the cycle's final cleanup."""
        old = SyntheticBrowser(connected=False, close_error=asyncio.CancelledError("synthetic"))
        launch = AsyncMock()
        admission = BrowserAdmission[SyntheticBrowser]({}, launch, MagicMock(), old)
        task = asyncio.create_task(admission.ensure(100))
        outcomes = await asyncio.gather(task, return_exceptions=True)
        require(condition=task.cancelled() and isinstance(outcomes[0], asyncio.CancelledError),
                message="close cancellation was swallowed")
        require(condition=admission.browser is old and launch.await_count == 0,
                message="cancelled close lost ownership")
