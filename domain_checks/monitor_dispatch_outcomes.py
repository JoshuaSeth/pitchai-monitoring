# Copyright (c) 2026 PitchAI. All rights reserved.
"""Dispatcher error classification and persisted outcome handling."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, cast

from domain_checks.monitor_dispatch_state import (
    disable_dispatch,
    dispatch_should_notify,
    notify_dispatch_disabled,
    record_dispatch,
)
from domain_checks.telegram import send_telegram_message

if TYPE_CHECKING:
    import httpx

    from domain_checks.monitor_dispatch_models import DispatchOutcome, DispatchRequest
    from domain_checks.monitor_runtime_state import RuntimeState
    from domain_checks.telegram import TelegramConfig
    from domain_checks.types import JsonObject

LOGGER = logging.getLogger("service-monitoring")
_TOO_MANY_REQUESTS = 429


def store_outcome(
    state: RuntimeState,
    request: DispatchRequest,
    outcome: DispatchOutcome,
) -> None:
    """Persist one normalized dispatcher outcome."""
    entry = cast(
        "JsonObject",
        {
            "ts": time.time(),
            "state_key": request.state_key,
            "title": request.title,
            **outcome,
        },
    )
    record_dispatch(state, entry)


async def handle_quota_failure(
    http_client: httpx.AsyncClient,
    telegram: TelegramConfig,
    dispatch_state: JsonObject,
    ui_url: str,
) -> None:
    """Disable dispatch and notify operators after a runner quota failure."""
    disable_dispatch(dispatch_state, reason="runner_quota_exceeded", cooldown_seconds=None)
    if dispatch_should_notify(dispatch_state, min_interval_seconds=3600.0):
        await notify_dispatch_disabled(
            http_client,
            telegram,
            dispatch_state,
            f"Dispatcher runner quota exceeded. Update PITCHAI_DISPATCH_TOKEN secret and redeploy. {ui_url}",
        )


async def handle_http_failure(
    http_client: httpx.AsyncClient,
    telegram: TelegramConfig,
    dispatch_state: JsonObject,
    request: DispatchRequest,
    error: httpx.HTTPStatusError,
) -> str:
    """Classify an HTTP status failure and return its queue-state label.

    Returns:
        The normalized HTTP queue-state label.
    """
    status_code = error.response.status_code
    suppress_notice = False
    if status_code in {401, 403}:
        disable_dispatch(dispatch_state, reason=f"auth_error_{status_code}", cooldown_seconds=None)
        suppress_notice = True
        if dispatch_should_notify(dispatch_state, min_interval_seconds=3600.0):
            await notify_dispatch_disabled(
                http_client,
                telegram,
                dispatch_state,
                f"Dispatcher returned {status_code}. Update PITCHAI_DISPATCH_TOKEN secret and redeploy.",
            )
    elif status_code == _TOO_MANY_REQUESTS:
        disable_dispatch(dispatch_state, reason="rate_limited_429", cooldown_seconds=1800.0)
        suppress_notice = True
        if dispatch_should_notify(dispatch_state, min_interval_seconds=1800.0):
            await notify_dispatch_disabled(
                http_client,
                telegram,
                dispatch_state,
                "Dispatcher rate-limited (429). Will retry automatically after cooldown.",
            )
    LOGGER.error("Dispatch failed title=%s status_code=%s", request.title, status_code)
    if not suppress_notice:
        await send_telegram_message(
            http_client,
            telegram,
            f"{request.title} dispatch escalation FAILED: HTTPStatusError: {error}",
        )
    return f"http_{status_code}"


async def handle_boundary_failure(
    http_client: httpx.AsyncClient,
    telegram: TelegramConfig,
    request: DispatchRequest,
    error: Exception,
) -> str:
    """Report a typed dispatcher IO boundary failure.

    Returns:
        The normalized error description.
    """
    description = f"{type(error).__name__}: {error}"
    LOGGER.error("Dispatch failed title=%s error=%s", request.title, description)
    await send_telegram_message(
        http_client,
        telegram,
        f"{request.title} dispatch escalation FAILED: {description}",
    )
    return description
