# Copyright (c) 2026 PitchAI. All rights reserved.
"""Read native shared-memory capacity and launch the existing Chromium process."""

from __future__ import annotations

import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .browser_launch import launch_options

if TYPE_CHECKING:
    from playwright.async_api import Browser, Playwright


@dataclass(frozen=True)
class NativeBrowserLauncher:
    """The Playwright owner and executable selected by the existing startup path."""

    playwright: Playwright
    executable: str

    async def launch(self) -> Browser:
        """Return native Chromium with the original shared-memory fallback arguments.

        Only filesystem capacity is read; no shared-memory file is created or
        trusted. Ordinary stat/conversion failure keeps the existing zero fallback.
        """
        shared_memory_bytes = 0
        with suppress(Exception):
            capacity = os.statvfs(Path("/dev") / "shm")
            shared_memory_bytes = int(capacity.f_frsize) * int(capacity.f_blocks)
        return await self.playwright.chromium.launch(**launch_options(shared_memory_bytes, self.executable))
