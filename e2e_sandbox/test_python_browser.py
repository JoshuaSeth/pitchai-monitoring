# Copyright (c) 2026 PitchAI. All rights reserved.
"""Synthetic submitted-test browser lifecycle checks with no live browser."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from playwright.async_api import Browser, BrowserContext, Page, Route

from domain_checks.browser_launch import base_chromium_arguments, chromium_arguments
from domain_checks.dft_test_support import require

from . import playwright_python
from .python_browser import BrowserSession, filter_route
from .python_execution import PreparedSubmission
from .python_result import RunFailureBoundary, RunResult

if TYPE_CHECKING:
    from domain_checks.event_bus_delivery import JsonObject

    from .python_module import MainEntry


class SandboxBrowserTests(unittest.IsolatedAsyncioTestCase):
    """Preserve argument policy, successful/failing runs and cancellation cleanup."""

    @staticmethod
    def test_argument_policy_keeps_fresh_lists_and_monitor_threshold() -> None:
        """Sandbox append policy does not change monitor's index-one insertion."""
        base = base_chromium_arguments()
        base.append("mutation")
        require(condition="mutation" not in base_chromium_arguments(), message="shared argument list mutated")
        threshold = 512 * 1024 * 1024
        require(condition=chromium_arguments(threshold) == base_chromium_arguments(), message="threshold changed")
        expected = base_chromium_arguments()
        expected.insert(1, "--disable-dev-shm-usage")
        require(condition=chromium_arguments(0) == expected, message="unknown memory policy changed")

    @staticmethod
    async def test_run_one_uses_real_entry_and_expected_launch_options() -> None:
        """The actual entry point uses a synthetic manager and no executable/socket."""
        closes = (AsyncMock(), AsyncMock(), AsyncMock())
        page = MagicMock(spec=Page, url="https://fixture.invalid", title=AsyncMock(return_value="fixture"),
                         set_default_timeout=MagicMock(), close=closes[0])
        context = MagicMock(spec=BrowserContext, route=AsyncMock(), new_page=AsyncMock(return_value=page),
                            close=closes[1])
        browser = MagicMock(spec=Browser, new_context=AsyncMock(return_value=context), close=closes[2])
        launch = AsyncMock(return_value=browser)
        manager = AsyncMock(__aenter__=AsyncMock(return_value=MagicMock(chromium=MagicMock(launch=launch))),
                            __aexit__=AsyncMock(return_value=False))
        module = ModuleType("synthetic_submission")
        entry = AsyncMock(return_value={"ignored": True})
        vars(module)["run"] = entry
        with (patch.object(playwright_python, "async_playwright", return_value=manager),
              patch.object(playwright_python, "find_chromium_executable", return_value="/synthetic/chromium"),
              patch.object(playwright_python, "_load_module_from_path", return_value=module),
              patch("time.perf_counter", side_effect=[10.0, 10.25])):
            result = await playwright_python.run_one(
                test_file=Path("synthetic.py"), base_url="https://fixture.invalid", artifacts_dir=Path("unused"),
                timeout_seconds=0.5, trace_on_failure=False,
            )
        launch.assert_awaited_once_with(headless=True, executable_path="/synthetic/chromium",
                                       args=[*base_chromium_arguments(), "--disable-dev-shm-usage"])
        entry.assert_awaited_once_with(page, "https://fixture.invalid", "unused")
        expected = RunResult("pass", 250.0, None, None, "https://fixture.invalid", "fixture", {},
                             browser_infra_error=False)
        require(condition=result == expected, message="success result changed")
        for close in closes:
            close.assert_awaited_once()

    @staticmethod
    async def test_failure_artifacts_and_trace_retry() -> None:
        """A trace-file failure still attempts stop; structured error log stays local."""
        with tempfile.TemporaryDirectory(prefix="sandbox-result-test-") as temporary:
            directory = Path(temporary)
            stop = AsyncMock(side_effect=[OSError("synthetic trace refusal"), None])
            context = MagicMock(spec=BrowserContext, tracing=MagicMock(stop=stop), close=AsyncMock())
            page = MagicMock(spec=Page, url="https://fixture.invalid", title=AsyncMock(return_value="failure"),
                             screenshot=AsyncMock(), close=AsyncMock())
            session = BrowserSession(cast("Browser", MagicMock(spec=Browser)), cast("BrowserContext", context),
                                     cast("Page", page), tracing_started=True)
            with patch("time.perf_counter", return_value=2.0):
                result = await session.failure(1.0, directory, RuntimeError("page crashed"), "synthetic traceback")
            require(condition=result.status == "infra_degraded", message="browser infra classified as product failure")
            require(condition=result.artifacts == {"failure_screenshot": "failure.png", "run_log": "run.log"},
                    message="failed trace created a receipt")
            expected_calls = 2
            require(condition=stop.await_count == expected_calls, message="trace fallback lost")
            saved = cast("JsonObject", json.loads((directory / "run.log").read_text(encoding="utf-8")))
            require(condition=saved["traceback"] == "synthetic traceback", message="diagnostic trace changed")

    @staticmethod
    async def test_cancellation_runs_existing_cleanup_without_result() -> None:
        """The submission boundary propagates cancellation and closes admitted resources."""
        entry = AsyncMock(side_effect=asyncio.CancelledError("synthetic cancel"))
        module = ModuleType("synthetic_cancel")
        vars(module)["main"] = entry
        close = AsyncMock()
        session = MagicMock(spec=BrowserSession, close=close, page=MagicMock(spec=Page))
        prepared = PreparedSubmission(1.0, "https://fixture.invalid", Path("unused"), 1000,
                                      module, cast("MainEntry", entry))
        results = await asyncio.gather(prepared.run(cast("BrowserSession", session)), return_exceptions=True)
        require(condition=isinstance(results[0], asyncio.CancelledError), message="cancellation became failure result")
        close.assert_awaited_once()

    @staticmethod
    async def test_route_abort_failure_still_continues() -> None:
        """An abort error follows the original continue path rather than dropping the route."""
        resume = AsyncMock()
        route = MagicMock(spec=Route, request=MagicMock(resource_type="image"),
                          abort=AsyncMock(side_effect=RuntimeError("synthetic abort error")), continue_=resume)
        await filter_route(cast("Route", route))
        resume.assert_awaited_once()

    @staticmethod
    def test_error_boundary_leaves_system_exit_loud() -> None:
        """Only ordinary exceptions are retained for a failure result."""
        boundary = RunFailureBoundary()
        require(condition=not boundary.__exit__(SystemExit, SystemExit(7), None), message="system exit consumed")
        error = ValueError("fixture")
        require(condition=boundary.__exit__(ValueError, error, None) and boundary.error is error,
                message="ordinary failure identity changed")
