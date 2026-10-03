# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing dispatch failure handling after explicit transport observation."""

from __future__ import annotations

import logging
import time
from http import HTTPStatus
from typing import TYPE_CHECKING

from .dispatch_notices import notify_disabled
from .dispatch_state import dispatch_disable
from .dispatch_transport import send_telegram_message

if TYPE_CHECKING:
    from httpx import HTTPStatusError

    from .dispatch_context import DispatchRequest, DispatchRuntime
    from .event_bus_delivery import JsonObject

LOGGER = logging.getLogger("service-monitoring")


def record_failure(runtime: DispatchRuntime, request: DispatchRequest, error: str, queue_state: str) -> None:
    """Record the established failure shape with failure-time start timestamps."""
    entry: JsonObject = {
        "ts": time.time(), "started_ts": time.time(), "state_key": request.state_key, "title": request.title,
        "bundle": None, "runner": None, "queue_state": queue_state, "ui_url": "",
        "ok": False, "error": error[:800], "agent_message": None,
    }
    runtime.records.record(entry, request.state_key, request.title)


async def handle_http_error(runtime: DispatchRuntime, request: DispatchRequest, error: HTTPStatusError) -> None:
    """Preserve permanent auth stops, rate-limit cooldown and failure notice order."""
    status = error.response.status_code
    text = f"HTTPStatusError: {error}"
    suppress_notice = False
    if status in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
        dispatch_disable(runtime.state, reason=f"auth_error_{status}", cooldown_seconds=None)
        suppress_notice = True
        await notify_disabled(
            runtime, f"Dispatcher returned {status}. Update PITCHAI_DISPATCH_TOKEN secret and redeploy.", interval=3600,
        )
    elif status == HTTPStatus.TOO_MANY_REQUESTS:
        dispatch_disable(runtime.state, reason="rate_limited_429", cooldown_seconds=30 * 60)
        suppress_notice = True
        await notify_disabled(
            runtime, "Dispatcher rate-limited (429). Will retry automatically after cooldown.", interval=1800,
        )
    LOGGER.error("Dispatch failed title=%s status_code=%s error=%s", request.title, status, text, exc_info=error)
    if not suppress_notice:
        await send_telegram_message(
            runtime.client, runtime.telegram, f"{request.title} dispatch escalation FAILED: {text}",
        )
    record_failure(runtime, request, text, f"http_{status}")


async def handle_error(runtime: DispatchRuntime, request: DispatchRequest, error: Exception) -> None:
    """Preserve generic failure forwarding; an error in this handler propagates."""
    text = f"{type(error).__name__}: {error}"
    LOGGER.error("Dispatch failed title=%s error=%s", request.title, text, exc_info=error)
    await send_telegram_message(runtime.client, runtime.telegram, f"{request.title} dispatch escalation FAILED: {text}")
    record_failure(runtime, request, text, "exception")
