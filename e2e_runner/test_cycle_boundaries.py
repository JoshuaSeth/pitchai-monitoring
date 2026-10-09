# Copyright (c) 2026 PitchAI. All rights reserved.
"""Synthetic native-runner admission, sequential failure and heartbeat integration."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from domain_checks.dft_test_support import require

from . import main
from .browser import BrowserLease
from .config import RunnerConfig
from .cycle import RunnerCycle, RunnerHooks
from .health_main import install_instrumentation
from .heartbeat import RunnerHeartbeat

if TYPE_CHECKING:
    from httpx import AsyncClient
    from playwright.async_api import Browser, Playwright


class CycleTests(unittest.IsolatedAsyncioTestCase):
    """Replace network/browser admission, preserving actual loop and hook calls."""

    @staticmethod
    async def test_code_jobs_continue_after_error_without_browser() -> None:
        """One code job error does not skip the next job or start Chromium."""
        cfg = RunnerConfig("u", "synthetic", "a", "t", 1, 1, trace_on_failure=False, code_exec_mode="local")
        claim = AsyncMock(return_value=[None, {"test_kind": "playwright_python", "run_id": "first"},
                                       {"test_kind": "puppeteer_js", "run_id": "second"}])
        execute = AsyncMock(side_effect=[ValueError("job"), None])
        launch = AsyncMock()
        cycle = RunnerCycle(cfg, cast("AsyncClient", MagicMock()), RunnerHooks(claim, execute))
        await cycle.iterate(cast("Playwright", MagicMock()), BrowserLease(launch))
        expected_jobs = 2
        require(condition=execute.await_count == expected_jobs, message="failure aborted subsequent jobs")
        launch.assert_not_awaited()

    @staticmethod
    async def test_backoff_reconnect_and_cancellation() -> None:
        """Admission keeps the original retry interval and never consumes cancellation."""
        close = AsyncMock()
        browser = cast("Browser", MagicMock(is_connected=MagicMock(return_value=True), close=close))
        launch = AsyncMock(side_effect=[ValueError("launch"), browser, asyncio.CancelledError])
        lease = BrowserLease(launch)
        playwright = cast("Playwright", MagicMock())
        require(condition=await lease.ensure(playwright, 100) is None, message="failed launch produced a browser")
        expected_next = 104
        require(condition=lease.next_try == expected_next, message="initial backoff changed")
        require(condition=await lease.ensure(playwright, 103) is None, message="retry preceded backoff")
        require(condition=await lease.ensure(playwright, 104) is browser, message="due retry failed")
        require(condition=await lease.ensure(playwright, 105) is browser, message="connected handle was replaced")
        lease.browser = None
        result = await asyncio.gather(lease.ensure(playwright, 106), return_exceptions=True)
        require(condition=isinstance(result[0], asyncio.CancelledError), message="cancellation became launch failure")

    @staticmethod
    async def test_smoke_path_retains_completion_and_close_failures() -> None:
        """Smoke mode propagates the job failure and still closes its admitted browser."""
        close = AsyncMock()
        browser = cast("Browser", MagicMock(close=close))
        execute = AsyncMock(side_effect=ValueError("completion"))
        cfg = RunnerConfig("u", "synthetic", "a", "t", 1, 1, trace_on_failure=False, code_exec_mode="local")
        cycle = RunnerCycle(cfg, cast("AsyncClient", MagicMock()), RunnerHooks(AsyncMock(), execute))
        result = await asyncio.gather(cycle.once(cast("Playwright", MagicMock()), [{}],
                                                 BrowserLease(AsyncMock(return_value=browser))), return_exceptions=True)
        require(condition=isinstance(result[0], ValueError), message="smoke failure was consumed")
        close.assert_awaited_once_with()

    @staticmethod
    async def test_native_once_consumes_installed_heartbeat_hooks() -> None:
        """The real entry path invokes the retained heartbeat wrappers around mocked IO."""
        cfg = RunnerConfig("u", "synthetic", "a", "t", 1, 1, trace_on_failure=False, code_exec_mode="local")
        client_context = MagicMock(__aenter__=AsyncMock(return_value=MagicMock()),
                                   __aexit__=AsyncMock(return_value=False))
        browser_context = MagicMock(__aenter__=AsyncMock(return_value=MagicMock()),
                                    __aexit__=AsyncMock(return_value=False))
        with TemporaryDirectory(prefix="runner-heartbeat-test-") as directory, \
                patch.object(main, "RegistryHttpClient", return_value=client_context), \
                patch.object(main, "async_playwright", return_value=browser_context), \
                patch.object(main, "_claim_jobs", new=AsyncMock(return_value=[{"test_kind": "puppeteer_js"}])), \
                patch.object(main, "_run_one_job", new=AsyncMock()), \
                patch.object(main, "_launch_browser", new=AsyncMock()) as launch:
            heartbeat = RunnerHeartbeat(path=Path(directory) / "heartbeat.json")
            install_instrumentation(heartbeat)
            await main.run_once(cfg)
            snapshot = heartbeat.snapshot()
        require(condition=snapshot["claim_attempts"] == snapshot["claim_successes"] == snapshot["completed_jobs"] == 1,
                message="native entry lost installed instrumentation")
        launch.assert_not_awaited()
