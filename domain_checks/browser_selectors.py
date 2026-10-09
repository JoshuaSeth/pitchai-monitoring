# Copyright (c) 2026 PitchAI. All rights reserved.
"""Required-selector waits with the original any-selector deadline and cleanup."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING, Literal, cast

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

if TYPE_CHECKING:
    from playwright.async_api import ElementHandle, Page

    from .common_check import SelectorCheck

type SelectorState = Literal["attached", "detached", "visible", "hidden"]


async def wait_selector(page: Page, check: SelectorCheck, timeout_ms: int) -> ElementHandle | None:
    """Delegate state validation to Playwright, retaining invalid-state behavior.

    Returns:
        Playwright's original handle or absent-handle result.
    """
    state = cast("SelectorState", check.state)
    return await page.wait_for_selector(check.selector, state=state, timeout=timeout_ms)


async def missing_selectors(page: Page, checks: list[SelectorCheck], timeout_ms: int) -> list[str]:
    """Wait for each all-required selector in order, catching only its timeout.

    Returns:
        The original selector strings for timed-out waits.
    """
    missing: list[str] = []
    for check in checks:
        with suppress(PlaywrightTimeoutError):
            _ = await wait_selector(page, check, timeout_ms)
            continue
        missing.append(check.selector)
    return missing


async def _first_success(pending: set[asyncio.Task[ElementHandle | None]], deadline: float) -> bool:
    while pending:
        remaining = max(0.0, deadline - asyncio.get_running_loop().time())
        if remaining <= 0:
            break
        done, still_pending = await asyncio.wait(pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
        pending.clear()
        pending.update(still_pending)
        if not done:
            break
        for task in done:
            with suppress(Exception):
                _ = await task
                return True
    return False


async def any_selector(page: Page, checks: list[SelectorCheck], timeout_ms: int) -> bool:
    """Wait concurrently for any successful selector and cancel outstanding waits.

    Returns:
        True immediately for no alternatives, otherwise only after a successful wait.
    """
    if not checks:
        return True
    pending = {asyncio.create_task(wait_selector(page, check, timeout_ms)) for check in checks}
    deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000.0)
    try:
        return await _first_success(pending, deadline)
    finally:
        for task in pending:
            _ = task.cancel()
        for task in pending:
            with suppress(asyncio.CancelledError, Exception):
                _ = await task
