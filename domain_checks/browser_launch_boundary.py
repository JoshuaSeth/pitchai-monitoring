# Copyright (c) 2026 PitchAI. All rights reserved.
"""Launch-error state and retry scheduling at the native browser boundary."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import MutableMapping
    from types import TracebackType

    from .browser_admission import BrowserStateValue

LOGGER = logging.getLogger("service-monitoring")


@dataclass(frozen=True)
class BrowserLaunchBoundary:
    """Preserve launch failure evidence and capped retry delay without swallowing cancellation."""

    state: MutableMapping[str, BrowserStateValue]
    now_ts: float

    def __enter__(self) -> Self:
        """Return this single launch boundary without altering retry state."""
        return self

    def __exit__(
        self, _error_type: type[BaseException] | None, error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> bool:
        """Record launch failures while preserving cancellation and system exits.

        Returns:
            True only after recording an ordinary launch exception.
        """
        if not isinstance(error, Exception):
            return False
        failures = int(self.state.get("browser_launch_fail_count") or 0) + 1
        self.state["browser_launch_fail_count"] = failures
        backoff = min(300.0, 5.0 * (2.0 ** min(failures, 6)))
        self.state["browser_launch_next_try_ts"] = self.now_ts + backoff
        self.state["browser_launch_last_error"] = f"{type(error).__name__}: {error}"
        LOGGER.warning(
            "Playwright launch failed; continuing HTTP-only retry_in=%ss error=%s",
            round(backoff), self.state["browser_launch_last_error"],
        )
        return True
