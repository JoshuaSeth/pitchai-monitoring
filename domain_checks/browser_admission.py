# Copyright (c) 2026 PitchAI. All rights reserved.
"""Browser connection reuse and launch admission for the existing cycle."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from .browser_launch_boundary import BrowserLaunchBoundary

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, MutableMapping

type BrowserStateValue = str | int | float | bool | None

_LOW_MEMORY_RETRY_SECONDS = 60.0


class BrowserConnection(Protocol):
    """Native connection operations needed for reuse and disconnected cleanup."""

    def is_connected(self) -> bool:
        """Read connectivity through the native implementation.

        Raises:
            NotImplementedError: A concrete browser implementation is required.
        """
        raise NotImplementedError

    async def close(self) -> None:
        """Release the connection through the native implementation.

        Raises:
            NotImplementedError: A concrete browser implementation is required.
        """
        raise NotImplementedError


@dataclass
class BrowserAdmission[BrowserT: BrowserConnection]:
    """Track the connection while the cycle retains final cleanup and persisted state."""

    state: MutableMapping[str, BrowserStateValue]
    launch: Callable[[], Awaitable[BrowserT]]
    memory: Callable[[], Mapping[str, int]]
    browser: BrowserT | None = None

    def memory_admitted(self, now_ts: float) -> bool:
        """Apply the existing low-memory delay without increasing launch failures.

        Returns:
            False only for a known available-memory value below the threshold.
        """
        minimum = int(self.state.get("browser_min_mem_available_mb") or 0)
        if minimum > 0:
            available = self.memory().get("MemAvailable")
            if isinstance(available, int):
                available_mb = int(available / 1024)
                if available_mb < minimum:
                    self.state["browser_launch_last_error"] = f"low_mem_available_mb={available_mb} < {minimum}"
                    self.state["browser_launch_next_try_ts"] = now_ts + _LOW_MEMORY_RETRY_SECONDS
                    return False
        return True

    async def ensure(self, now_ts: float) -> BrowserT | None:
        """Reuse a connected browser or attempt launch at the original retry boundary.

        Returns:
            The current/new browser, or None when admission or launch fails.
        """
        if self.browser is not None:
            # Native connection/close failures must not stop HTTP-only monitoring.
            with suppress(Exception):
                if self.browser.is_connected():
                    return self.browser
            with suppress(Exception):
                await self.browser.close()
            self.browser = None
        next_try = float(self.state.get("browser_launch_next_try_ts") or 0.0)
        if next_try > 0.0 and now_ts < next_try:
            return None
        if not self.memory_admitted(now_ts):
            self.browser = None
            return None
        with BrowserLaunchBoundary(self.state, now_ts):
            self.browser = await self.launch()
            self.state["browser_launch_fail_count"] = 0
            self.state["browser_launch_next_try_ts"] = 0.0
            self.state["browser_launch_last_error"] = None
            return self.browser
        self.browser = None
        return None
