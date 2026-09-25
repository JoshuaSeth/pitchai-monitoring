# Copyright (c) 2026 PitchAI. All rights reserved.
"""Regression tests for submitted Python browser-resource ownership."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, NamedTuple, cast, final

import pytest

from e2e_registry.testing import require_test_condition
from e2e_sandbox.browser_session import start_session
from e2e_sandbox.models import SandboxRequest
from e2e_sandbox.runtime import execute_with_playwright

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from playwright.async_api import Playwright, Route

    type RouteCallback = Callable[[Route], Awaitable[None]]

_EXPECTED_VIEWPORT_WIDTH = 1280


@final
class FailingPageContext:
    """Context double that fails after route setup but before page ownership."""

    def __init__(self) -> None:
        """Initialize cleanup and setup counters."""
        self.close_calls = 0
        self.new_page_calls = 0

    async def route(self, _pattern: str, _handler: RouteCallback) -> None:
        """Accept the sandbox route policy."""

    async def new_page(self) -> None:
        """Fail at the partial-session boundary under test.

        Raises:
            RuntimeError: Always, to simulate page creation failure.
        """
        self.new_page_calls += 1
        message = "page setup failed"
        raise RuntimeError(message)

    async def close(self) -> None:
        """Record context cleanup."""
        self.close_calls += 1


@final
class FakeBrowser:
    """Browser double that owns one failing context."""

    def __init__(self) -> None:
        """Initialize an owned context and cleanup counter."""
        self.context = FailingPageContext()
        self.close_calls = 0

    async def new_context(self, *, viewport: dict[str, int]) -> FailingPageContext:
        """Return the configured context double."""
        require_test_condition(
            condition=viewport["width"] == _EXPECTED_VIEWPORT_WIDTH,
            message="the viewport contract changed",
        )
        return self.context

    async def close(self) -> None:
        """Record browser cleanup."""
        self.close_calls += 1


@final
class FakeChromium:
    """Chromium launcher double with an observable launch count."""

    def __init__(self) -> None:
        """Initialize an owned browser and launch counter."""
        self.browser = FakeBrowser()
        self._launch_calls = 0

    async def launch(
        self,
        *,
        headless: bool,
        executable_path: str,
        args: list[str],
    ) -> FakeBrowser:
        """Return the browser double while validating the launch contract."""
        require_test_condition(condition=headless, message="submitted tests must launch headlessly")
        require_test_condition(condition=bool(executable_path), message="a browser path is required")
        require_test_condition(condition="--no-sandbox" in args, message="the hardened launch arguments changed")
        self._launch_calls += 1
        return self.browser

    def launch_count(self) -> int:
        """Return how often browser startup was attempted."""
        return self._launch_calls


class FakePlaywright(NamedTuple):
    """Minimal Playwright double used through an explicit type boundary."""

    chromium: FakeChromium


def _sandbox_request(*, test_file: Path, artifacts_dir: Path) -> SandboxRequest:
    return SandboxRequest(
        test_file=test_file,
        base_url="https://target.invalid",
        artifacts_dir=artifacts_dir,
        timeout_seconds=1.0,
        trace_on_failure=False,
    )


@pytest.mark.asyncio
async def test_import_failure_happens_before_browser_startup(tmp_path: Path) -> None:
    """Invalid submitted imports must not create resources that need cleanup."""
    test_file = tmp_path / "invalid_submission.py"
    _ = test_file.write_text("this is not valid Python !!!\n", encoding="utf-8")
    fake_playwright = FakePlaywright(chromium=FakeChromium())

    with pytest.raises(SyntaxError):
        await execute_with_playwright(
            _sandbox_request(test_file=test_file, artifacts_dir=tmp_path / "artifacts"),
            started_at=time.perf_counter(),
            playwright=cast("Playwright", cast("object", fake_playwright)),
        )

    require_test_condition(
        condition=fake_playwright.chromium.launch_count() == 0,
        message="the browser must not start before a submitted module imports successfully",
    )


@pytest.mark.asyncio
async def test_partial_browser_startup_closes_created_resources(tmp_path: Path) -> None:
    """A later setup failure must close its already-created context and browser."""
    fake_playwright = FakePlaywright(chromium=FakeChromium())
    request = _sandbox_request(test_file=tmp_path / "unused.py", artifacts_dir=tmp_path / "artifacts")

    with pytest.raises(RuntimeError, match="page setup failed"):
        await start_session(
            cast("Playwright", cast("object", fake_playwright)),
            request,
            browser_path_resolver=lambda: "/opt/chromium",
        )

    require_test_condition(
        condition=fake_playwright.chromium.browser.context.new_page_calls == 1,
        message="page setup must be attempted exactly once",
    )
    require_test_condition(
        condition=fake_playwright.chromium.browser.context.close_calls == 1,
        message="a partially-created context must close exactly once",
    )
    require_test_condition(
        condition=fake_playwright.chromium.browser.close_calls == 1,
        message="a partially-created browser must close exactly once",
    )
