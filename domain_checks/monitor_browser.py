# Copyright (c) 2026 PitchAI. All rights reserved.
"""Playwright browser launch, backoff, and degradation lifecycle."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.async_api import Error as PlaywrightError

from domain_checks.common_browser_runtime import chromium_launch_arguments
from domain_checks.monitor_host import format_browser_health_hint, read_linux_meminfo_kb
from domain_checks.monitor_values import float_value, int_value

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserType

    from domain_checks.monitor_context import DomainCycle, MonitorContext
    from domain_checks.types import JsonObject

LOGGER = logging.getLogger("service-monitoring")
_DEGRADED_NOTICE_INTERVAL_SECONDS = 6 * 3600
_RECOVERY_CYCLES = 5
_MIN_LARGE_SHM_BYTES = 512 * 1024 * 1024


def _launch_args() -> list[str]:
    shared_memory_path = Path(os.sep) / "dev" / "shm"
    try:
        shared_memory = os.statvfs(shared_memory_path)
    except OSError:
        shm_bytes = 0
    else:
        shm_bytes = shared_memory.f_frsize * shared_memory.f_blocks
    return chromium_launch_arguments(
        disable_dev_shm=shm_bytes < _MIN_LARGE_SHM_BYTES,
    )


@dataclass
class BrowserManager:
    """Own one browser process with resource guards and retry backoff."""

    browser_type: BrowserType
    executable_path: str
    minimum_available_mb: int
    state: JsonObject
    browser: Browser | None = None

    async def _close_current(self) -> None:
        if self.browser is None:
            return
        try:
            await self.browser.close()
        except PlaywrightError:
            LOGGER.debug("Unable to close disconnected Playwright browser", exc_info=True)
        self.browser = None

    async def ensure(self, now_ts: float) -> Browser | None:
        """Return a connected browser or record a bounded launch failure.

        Returns:
            A connected browser, or ``None`` during resource/backoff degradation.
        """
        if self.browser is not None and self.browser.is_connected():
            return self.browser
        await self._close_current()
        next_try = float_value(self.state.get("launch_next_try_ts"))
        if now_ts < next_try:
            return None
        memory = read_linux_meminfo_kb()
        available_kb = memory.get("MemAvailable")
        if available_kb is not None and available_kb // 1024 < self.minimum_available_mb:
            available_mb = available_kb // 1024
            self.state["launch_last_error"] = f"low_mem_available_mb={available_mb} < {self.minimum_available_mb}"
            self.state["launch_next_try_ts"] = now_ts + 60.0
            return None
        try:
            self.browser = await self.browser_type.launch(
                headless=True,
                args=_launch_args(),
                executable_path=self.executable_path,
            )
        except (PlaywrightError, OSError) as exc:
            failures = int_value(self.state.get("launch_fail_count")) + 1
            backoff = min(300.0, 5.0 * (1 << min(failures, 6)))
            self.state["launch_fail_count"] = failures
            self.state["launch_next_try_ts"] = now_ts + backoff
            self.state["launch_last_error"] = f"{type(exc).__name__}: {exc}"
            LOGGER.warning("Playwright launch failed retry_in=%ss error=%s", round(backoff), exc)
            return None
        self.state["launch_fail_count"] = 0
        self.state["launch_next_try_ts"] = 0.0
        self.state["launch_last_error"] = None
        return self.browser

    async def restart(self, now_ts: float) -> Browser | None:
        """Close a degraded process and attempt a guarded relaunch.

        Returns:
            The replacement browser when launch succeeds.
        """
        await self._close_current()
        return await self.ensure(now_ts)

    async def close(self) -> None:
        """Close the owned browser process."""
        await self._close_current()
        LOGGER.debug("Playwright browser manager closed")


async def run_browser_lifecycle(
    ctx: MonitorContext,
    cycle: DomainCycle,
    manager: BrowserManager,
) -> None:
    """Record browser health, notify degradation, and manage recovery."""
    state = ctx.state.metadata.browser
    ctx.append_signal(
        "browser",
        [
            cycle.started_ts,
            int(not cycle.browser_degraded),
            int(bool(state.get("degraded_active"))),
            int_value(state.get("launch_fail_count")),
        ],
    )
    if cycle.browser_degraded:
        now = time.time()
        if not bool(state.get("degraded_active")):
            state["degraded_active"] = True
            state["first_seen_ts"] = now
        state["recover_streak"] = 0
        last_notice = float_value(state.get("last_notice_ts"))
        if last_notice <= 0.0 or now - last_notice >= _DEGRADED_NOTICE_INTERVAL_SECONDS:
            state["last_notice_ts"] = now
            error = state.get("launch_last_error")
            lines = [
                "Monitor warning: Playwright browser checks are degraded (browser crash/close detected).",
                "Continuing with HTTP-only results and attempting to restart the browser process.",
            ]
            if isinstance(error, str) and error.strip():
                lines.append(f"Last browser error: {error.strip()[:500]}")
            health_hint = format_browser_health_hint()
            if health_hint:
                lines.append(f"Host: {health_hint}")
            await ctx.alert("\n".join(lines))
            ctx.events.append(
                "browser_degraded_notice",
                occurred_at=now,
                last_error=error[:800] if isinstance(error, str) else None,
                host_hint=health_hint[:500] or None,
            )
            _ = ctx.events.persist()
        _ = await manager.restart(now)
        return
    if not bool(state.get("degraded_active")):
        return
    streak = int_value(state.get("recover_streak")) + 1
    state["recover_streak"] = streak
    if streak >= _RECOVERY_CYCLES:
        state["degraded_active"] = False
        state["first_seen_ts"] = 0.0
        state["recover_streak"] = 0
        ctx.events.append("browser_recovered", occurred_at=time.time())
