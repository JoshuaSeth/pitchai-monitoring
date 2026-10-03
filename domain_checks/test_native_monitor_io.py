# Copyright (c) 2026 PitchAI. All rights reserved.
"""Native transport defaults and Chromium capacity fallback without external IO."""

from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from .browser_launch import launch_options
from .dft_test_support import require
from .monitor_transport import MonitorHttpClient
from .native_browser import NativeBrowserLauncher

if TYPE_CHECKING:
    from playwright.async_api import Browser, Playwright


class NativeIoTests(unittest.IsolatedAsyncioTestCase):
    """Every native launch/stat is synthetic; the client opens no requests."""

    @staticmethod
    async def test_client_preserves_native_defaults_and_closes() -> None:
        """The explicit client owns only the user agent and native context lifetime."""
        with patch("httpx.AsyncClient.send", new=AsyncMock(side_effect=AssertionError("outgoing"))) as send:
            async with MonitorHttpClient() as client:
                require(condition=client.headers["User-Agent"] == "PitchAI Service Monitoring Bot",
                        message="monitor user agent changed")
                require(condition=not client.is_closed, message="transport prematurely closed")
            require(condition=client.is_closed, message="native transport leaked")
        send.assert_not_called()

    @staticmethod
    async def test_capacity_and_read_failure_keep_existing_arguments() -> None:
        """Both a sufficient shmfs and a failed read reach the original argument builder."""
        browser = cast("Browser", MagicMock())
        launch = AsyncMock(return_value=browser)
        playwright = cast("Playwright", MagicMock(chromium=MagicMock(launch=launch)))
        owner = NativeBrowserLauncher(playwright, "/synthetic-browser")
        capacity = os.statvfs_result((4096, 4096, 262144, 0, 0, 0, 0, 0, 0, 255))
        with patch("domain_checks.native_browser.os.statvfs", return_value=capacity) as stat:
            actual = await owner.launch()
        stat.assert_called_once_with(Path("/dev") / "shm")
        launch.assert_awaited_once_with(**launch_options(4096 * 262144, "/synthetic-browser"))
        require(condition=actual is browser, message="browser identity changed")
        launch.reset_mock()
        with patch("domain_checks.native_browser.os.statvfs", side_effect=OSError("synthetic unavailable")):
            _ = await owner.launch()
        launch.assert_awaited_once_with(**launch_options(0, "/synthetic-browser"))

    @staticmethod
    async def test_capacity_cancellation_prevents_launch() -> None:
        """Cancellation is not converted into the ordinary zero-capacity fallback."""
        launch = AsyncMock()
        owner = NativeBrowserLauncher(cast("Playwright", MagicMock(chromium=MagicMock(launch=launch))), "fixture")
        with patch("domain_checks.native_browser.os.statvfs", side_effect=asyncio.CancelledError):
            result = await asyncio.gather(owner.launch(), return_exceptions=True)
        require(condition=isinstance(result[0], asyncio.CancelledError), message="stat cancellation suppressed")
        launch.assert_not_awaited()
