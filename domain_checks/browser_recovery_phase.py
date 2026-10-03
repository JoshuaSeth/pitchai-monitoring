# Copyright (c) 2026 PitchAI. All rights reserved.
"""Browser degradation notices and restart ordering inside the existing cycle."""

from __future__ import annotations

import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .dispatch_transport import redact_telegram_response, send_telegram_message

if TYPE_CHECKING:
    from collections.abc import Callable

    from .browser_admission import BrowserAdmission, BrowserConnection
    from .probe_frame import ProbeFrame

LOGGER = logging.getLogger("service-monitoring")
_HEALTHY_CYCLES_FOR_RECOVERY = 5


@dataclass(frozen=True)
class BrowserRecoveryPhase[BrowserT: BrowserConnection]:
    """Keep the same browser handle, mutable monitor state and persistence callback."""

    admission: BrowserAdmission[BrowserT]
    health_hint: Callable[[], str | None]
    persist_notice: Callable[[], None]

    async def run(self, frame: ProbeFrame, *, degraded: bool) -> None:
        """Record pre-transition health, then retain original notice/restart sequencing."""
        state = self.admission.state
        frame.signals.append("browser", [float(frame.started), 0 if degraded else 1,
            1 if bool(state.get("browser_degraded_active")) else 0,
            int(state.get("browser_launch_fail_count") or 0)])
        if not degraded:
            self._recover(frame)
            return
        now = time.time()
        if not state.get("browser_degraded_active", False):
            state["browser_degraded_active"] = True
            state["browser_degraded_first_seen_ts"] = now
            state["browser_degraded_recover_streak"] = 0
        state["browser_degraded_recover_streak"] = 0
        last_notice = float(state.get("browser_degraded_last_notice_ts") or 0.0)
        minimum = float(state.get("browser_degraded_notice_min_interval_seconds") or (6 * 3600))
        if last_notice <= 0.0 or now - last_notice >= minimum:
            await self._notice(frame, now)
        # A failed close must still permit HTTP monitoring and a new admission
        # attempt. Cancellation preserves ownership of the existing handle.
        with suppress(Exception):
            if self.admission.browser is not None:
                await self.admission.browser.close()
        self.admission.browser = None
        _ = await self.admission.ensure(now)

    async def _notice(self, frame: ProbeFrame, now: float) -> None:
        state = self.admission.state
        state["browser_degraded_last_notice_ts"] = now
        LOGGER.warning("Playwright browser checks degraded; restarting browser process")
        hint = self.health_hint()
        error = state.get("browser_launch_last_error")
        lines = [
            "Monitor warning: Playwright browser checks are degraded (browser crash/close detected).",
            "Continuing with HTTP-only results and attempting to restart the browser process.",
        ]
        if isinstance(error, str) and error.strip():
            lines.append(f"Last browser error: {error.strip()[:500]}")
        if hint:
            lines.append(f"Host: {hint}")
        ok, response = await send_telegram_message(frame.channels.client, frame.channels.telegram,
                                                    "\n".join(lines).strip())
        LOGGER.warning("Browser degraded notice sent ok=%s telegram=%s", ok, redact_telegram_response(response))
        frame.event("browser_degraded_notice", float(now), {
            "last_error": error.strip()[:800] if isinstance(error, str) else None,
            "host_hint": hint.strip()[:500] if isinstance(hint, str) else None,
        })
        # Preserve the immediate timestamp write before risky restart work;
        # the owning cycle retains payload construction and its failure counter.
        self.persist_notice()

    def _recover(self, frame: ProbeFrame) -> None:
        state = self.admission.state
        if state.get("browser_degraded_active"):
            streak = int(state.get("browser_degraded_recover_streak") or 0) + 1
            state["browser_degraded_recover_streak"] = streak
            if streak >= _HEALTHY_CYCLES_FOR_RECOVERY:
                state["browser_degraded_active"] = False
                state["browser_degraded_first_seen_ts"] = 0.0
                state["browser_degraded_recover_streak"] = 0
                LOGGER.info("Playwright browser checks recovered")
                frame.event("browser_recovered", time.time(), {})
