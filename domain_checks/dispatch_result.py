# Copyright (c) 2026 PitchAI. All rights reserved.
"""Interpret the existing remote run result before recording completion."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from .dispatch_notices import forward_message, forward_no_message, notify_disabled
from .dispatch_state import dispatch_disable

if TYPE_CHECKING:
    from .dispatch_context import DispatchRequest, DispatchRun, DispatchRuntime

LOGGER = logging.getLogger("service-monitoring")
QUOTA_MARKERS = ("quota exceeded", "billing details", "insufficient_quota")


async def complete_message(runtime: DispatchRuntime, request: DispatchRequest, run: DispatchRun, message: str) -> None:
    """Forward a result before retaining the same bounded agent text."""
    header = f"{request.title} (bundle={run.bundle})\n{run.ui}\n\n"
    await forward_message(runtime, request.title, run.bundle, header + message)
    entry = {"ts": time.time(), **run.entry(request), "ok": True, "error": None, "agent_message": message[:12_000]}
    runtime.records.record(entry, request.state_key, request.title)


async def complete_without_message(
    runtime: DispatchRuntime, request: DispatchRequest, run: DispatchRun, error: str,
) -> None:
    """Preserve quota-stop versus ordinary missing-result semantics."""
    text = error.strip()
    lowered = text.lower()
    quota = any(marker in lowered for marker in QUOTA_MARKERS)
    if quota:
        dispatch_disable(runtime.state, reason="runner_quota_exceeded", cooldown_seconds=None)
        await notify_disabled(
            runtime,
            f"Dispatcher runner quota exceeded. Update PITCHAI_DISPATCH_TOKEN secret and redeploy. {run.ui}",
            interval=3600,
        )
        LOGGER.warning(
            "Dispatch disabled due to runner quota title=%s bundle=%s error=%s",
            request.title, run.bundle, text[:500] if text else None,
        )
    else:
        extra = f" Last error: {text[:300]}" if text else ""
        notice = f"{request.title} finished (bundle={run.bundle}) but no agent message was found.{extra} {run.ui}"
        await forward_no_message(runtime, request.title, run.bundle, notice)
    default_error = "runner_quota_exceeded" if quota else "no_agent_message"
    entry = {
        "ts": time.time(), **run.entry(request), "ok": not quota and run.queue_state == "processed",
        "error": text[:800] if text else default_error, "agent_message": None,
    }
    runtime.records.record(entry, request.state_key, request.title)
