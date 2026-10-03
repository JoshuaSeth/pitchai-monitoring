# Copyright (c) 2026 PitchAI. All rights reserved.
"""Submitted-test browser resource boundaries and best-effort failure artifacts."""

from __future__ import annotations

import json
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

from domain_checks.browser_errors import is_browser_infra_error

from .python_result import RunResult, safe_str, write_text

if TYPE_CHECKING:
    from pathlib import Path

    from playwright.async_api import Browser, BrowserContext, Page, Route


async def filter_route(route: Route) -> None:
    """Keep image/media/font abort with the existing continue fallback."""
    with suppress(Exception):
        if route.request.resource_type in {"image", "media", "font"}:
            await route.abort()
            return
    await route.continue_()


async def route_filter(context: BrowserContext) -> None:
    """Install the same best-effort bandwidth filter on this isolated context."""
    with suppress(Exception):
        await context.route("**/*", filter_route)


@dataclass
class BrowserSession:
    """Already-created resources; startup allocation retains its original boundary."""

    browser: Browser
    context: BrowserContext
    page: Page
    tracing_started: bool = False

    async def start_trace(self, *, enabled: bool) -> None:
        """Keep tracing optional and mark it started only after success."""
        if enabled:
            with suppress(Exception):
                await self.context.tracing.start(screenshots=True, snapshots=True, sources=False)
                self.tracing_started = True

    async def success(self, started: float, artifacts: dict[str, str]) -> RunResult:
        """Observe elapsed time, URL and title before stopping successful tracing.

        Returns:
            The same successful result fields and artifact dictionary.
        """
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        final_url = safe_str(self.page.url)
        title = None
        with suppress(Exception):
            title = safe_str(await self.page.title(), max_len=500)
        if self.tracing_started:
            with suppress(Exception):
                await self.context.tracing.stop()
        return RunResult("pass", round(elapsed_ms, 3), None, None, final_url or None, title, artifacts,
                         browser_infra_error=False)

    async def failure(self, started: float, directory: Path, error: Exception, trace: str) -> RunResult:
        """Collect the existing failure metadata and best-effort screenshot/trace.

        Returns:
            Failure/infra result with the original error and diagnostic artifacts.
        """
        infra = is_browser_infra_error(error)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        final_url, title = None, None
        with suppress(Exception):
            final_url = safe_str(self.page.url) or None
        with suppress(Exception):
            title = safe_str(await self.page.title(), max_len=500)
        artifacts: dict[str, str] = {}
        with suppress(Exception):
            await self.page.screenshot(path=str(directory / "failure.png"), full_page=True)
            artifacts["failure_screenshot"] = "failure.png"
        await self.stop_failed_trace(directory, artifacts)
        status = "infra_degraded" if infra else "fail"
        kind, message = type(error).__name__, safe_str(error, max_len=2000)
        write_text(directory / "run.log", json.dumps({
            "status": status, "error_kind": kind, "error_message": message,
            "final_url": final_url, "title": title, "browser_infra_error": bool(infra),
            "traceback": safe_str(trace, max_len=50_000),
        }, ensure_ascii=False, sort_keys=True, indent=2))
        artifacts.setdefault("run_log", "run.log")
        return RunResult(status, round(elapsed_ms, 3), kind, message, final_url, title, artifacts, bool(infra))

    async def stop_failed_trace(self, directory: Path, artifacts: dict[str, str]) -> None:
        """Keep unpersisted trace cleanup after a failed trace-file write."""
        if not self.tracing_started:
            return
        with suppress(Exception):
            await self.context.tracing.stop(path=str(directory / "trace.zip"))
            artifacts["trace_zip"] = "trace.zip"
            return
        with suppress(Exception):
            await self.context.tracing.stop()

    async def close(self) -> None:
        """Close page, context and browser in order, retaining ordinary-error tolerance."""
        with suppress(Exception):
            await self.page.close()
        with suppress(Exception):
            await self.context.close()
        with suppress(Exception):
            await self.browser.close()
