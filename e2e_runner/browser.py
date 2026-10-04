# Copyright (c) 2026 PitchAI. All rights reserved.
"""Runner-specific Chromium admission and retry ownership."""

from __future__ import annotations

import logging
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from domain_checks.browser_failure import BrowserFailure
from domain_checks.browser_launch import base_chromium_arguments
from domain_checks.common_check import find_chromium_executable

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from playwright.async_api import Browser, Playwright

LOGGER = logging.getLogger("e2e-runner")
_MINIMUM_SHARED_MEMORY = 512 * 1024 * 1024
type BrowserLaunch = Callable[[Playwright], Awaitable[Browser]]


async def launch_browser(playwright: Playwright) -> Browser:
    """Launch with shared flags while retaining the runner's unknown-memory policy.

    Returns:
        The native Chromium browser.

    Raises:
        RuntimeError: No executable has been configured or discovered.
    """
    executable = find_chromium_executable()
    if not executable:
        message = "Could not find chromium executable (set CHROMIUM_PATH)"
        raise RuntimeError(message)
    args = base_chromium_arguments()
    size = 0
    # An unavailable measurement historically omits the runner's fallback flag.
    with suppress(Exception):
        stats = os.statvfs(Path("/dev") / "shm")
        size = int(stats.f_frsize) * int(stats.f_blocks)
    if size and size < _MINIMUM_SHARED_MEMORY:
        args.insert(1, "--disable-dev-shm-usage")
    return await playwright.chromium.launch(headless=True, executable_path=executable, args=args)


@dataclass
class BrowserLease:
    """Retain the browser handle and original exponential admission backoff."""

    launch: BrowserLaunch
    browser: Browser | None = None
    failures: int = 0
    next_try: float = 0.0

    async def ensure(self, playwright: Playwright, now: float) -> Browser | None:
        """Return a connected handle or attempt admission when the backoff is due."""
        if self.browser is not None:
            with suppress(Exception):
                if self.browser.is_connected():
                    return self.browser
            await self.close()
            self.browser = None
        if self.next_try > 0.0 and now < self.next_try:
            return None
        with BrowserFailure() as failure:
            self.browser = await self.launch(playwright)
        if failure.error is None:
            self.failures = 0
            self.next_try = 0.0
            LOGGER.info("Chromium launched ok")
            return self.browser
        self.failures += 1
        backoff = min(120.0, 2.0 * cast("int", 2 ** min(self.failures, 6)))
        self.next_try = now + backoff
        self.browser = None
        LOGGER.warning("Chromium launch failed; backoff_seconds=%s fail_count=%s", backoff, self.failures)
        return None

    async def close(self) -> None:
        """Attempt ordinary-error-tolerant close, preserving cancellation propagation."""
        if self.browser is not None:
            with suppress(Exception):
                await self.browser.close()
