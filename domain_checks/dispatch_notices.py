# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing dispatch notices through the configured Telegram transport."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .dispatch_state import dispatch_should_notify
from .dispatch_transport import redact_telegram_response, send_telegram_message, send_telegram_message_chunked

if TYPE_CHECKING:
    from .dispatch_context import DispatchRuntime

LOGGER = logging.getLogger("service-monitoring")


async def notify_disabled(runtime: DispatchRuntime, details: str, *, interval: float) -> None:
    """Apply existing notice cadence and format disablement without changing its cause."""
    if not dispatch_should_notify(runtime.state, min_interval_seconds=interval):
        return
    reason = runtime.state.get("disabled_reason") or "unknown"
    until = runtime.state.get("disabled_until_monotonic")
    permanent = until is None and runtime.state.get("enabled") is False
    until_text = "until token is fixed/restarted" if permanent else "temporarily"
    message = (
        "Dispatcher escalation is disabled.\n"
        f"Reason: {reason}\nStatus: {until_text}\nDetails: {details}"
    )
    await send_telegram_message(runtime.client, runtime.telegram, message)


async def forward_no_message(runtime: DispatchRuntime, title: str, bundle: str, text: str) -> None:
    """Send and log the existing missing-message notice; no dispatch result is inferred."""
    ok, response = await send_telegram_message(runtime.client, runtime.telegram, text)
    LOGGER.warning(
        "Dispatch finished no_message title=%s bundle=%s sent_ok=%s telegram=%s",
        title, bundle, ok, redact_telegram_response(response),
    )


async def forward_message(runtime: DispatchRuntime, title: str, bundle: str, text: str) -> None:
    """Send existing chunked output and retain only the established sanitized log fields."""
    ok, responses = await send_telegram_message_chunked(runtime.client, runtime.telegram, text)
    last = responses[-1] if responses else {}
    LOGGER.info(
        "Dispatch finished title=%s bundle=%s telegram_ok=%s telegram_last=%s",
        title, bundle, ok, redact_telegram_response(last),
    )
