# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared Chromium launch policy for StepFlow runner jobs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain_checks.common_check import chromium_launch_arguments, find_chromium_executable

if TYPE_CHECKING:
    from playwright.async_api import Browser, Playwright


class BrowserUnavailableError(RuntimeError):
    """Raised when the runner cannot locate a Chromium executable."""


async def launch_browser(playwright: Playwright) -> Browser:
    """Launch the runner's shared Chromium process.

    Returns:
        A connected Playwright browser.

    Raises:
        BrowserUnavailableError: If no Chromium executable is configured or installed.
    """
    chromium_path = find_chromium_executable()
    if chromium_path is None:
        message = "Could not find Chromium executable; set CHROMIUM_PATH"
        raise BrowserUnavailableError(message)
    return await playwright.chromium.launch(
        headless=True,
        executable_path=chromium_path,
        args=chromium_launch_arguments(disable_dev_shm=True),
    )
