# Copyright (c) 2026 PitchAI. All rights reserved.
"""Scheduling and final resource ownership for the existing asynchronous loop."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .browser_admission import BrowserConnection
from .meta_phase import CycleTiming

if TYPE_CHECKING:
    from .cycle_iteration import CycleIteration
    from .cycle_startup import CycleLimits

LOGGER = logging.getLogger("service-monitoring")


@dataclass(frozen=True)
class CycleRunner[BrowserT: BrowserConnection]:
    """Retain initial admission, repeat timing and the original cleanup boundary."""

    iteration: CycleIteration[BrowserT]
    limits: CycleLimits

    async def run(self, *, once: bool) -> int:
        """Run the existing loop with cleanup after its original admission point.

        Returns:
            Zero after a successful single cycle; repeated mode runs until interrupted.

        A failure of initial admission remains outside final cleanup. During the
        loop, DFT closes before the current browser, preserving failure precedence.
        """
        admission = self.iteration.phases.domains.browser
        await admission.ensure(time.time())
        try:
            return await self._repeat(once=once)
        finally:
            self.iteration.persistence.dft.close()
            if admission.browser is not None:
                await admission.browser.close()

    async def _repeat(self, *, once: bool) -> int:
        while True:
            started = time.time()
            LOGGER.info("Running check cycle")
            frame = await self.iteration.run(started)
            if once:
                return 0
            elapsed = time.time() - started
            await self.iteration.phases.meta.run(frame, CycleTiming(
                self.limits.interval, elapsed, self.iteration.persistence.health.write_fail_streak,
                self.iteration.phases.domains.browser.browser,
                self.limits.check_concurrency, self.limits.browser_concurrency,
            ))
            await self.iteration.persistence.flush(self.iteration.channels.client)
            self.iteration.persistence.persist("post_meta")
            sleep_for = max(0.0, self.limits.interval - elapsed)
            LOGGER.info("Cycle complete elapsed_seconds=%s sleep_seconds=%s", round(elapsed, 3), round(sleep_for, 3))
            await asyncio.sleep(sleep_for)
