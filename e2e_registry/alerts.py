# Copyright (c) 2026 PitchAI. All rights reserved.
"""Registry alert admission and its existing dispatch/record/forward order."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from domain_checks.dispatch_client import (
    DispatchConfig,
    dispatch_job,
    extract_last_agent_message_from_exec_log,
    extract_last_error_message_from_exec_log,
    get_run_log_tail,
    run_ui_url,
    wait_for_terminal_status,
)
from domain_checks.dispatch_transport import send_telegram_message_chunked
from domain_checks.message_templates import dispatch_read_only_rules as _dispatch_read_only_rules
from domain_checks.telegram import TelegramConfig

from .alert_messages import (
    build_dispatch_prompt_for_failure,
    build_failure_telegram_message,
    build_recovery_telegram_message,
)
from .alert_messages import public_url as _public_url
from .alert_messages import safe_json as _safe_json
from .alert_records import DispatchRecord

if TYPE_CHECKING:
    from httpx import AsyncClient

    from domain_checks.event_bus_delivery import JsonObject

    from .settings import RegistrySettings

__all__ = [
    "_dispatch_read_only_rules", "_public_url", "_safe_json", "build_dispatch_prompt_for_failure",
    "build_failure_telegram_message", "build_recovery_telegram_message", "maybe_dispatch_failure_investigation",
    "maybe_send_failure_alert",
]

LOGGER = logging.getLogger("e2e-registry")
DISPATCH_STATE_KEY = "e2e-registry.failure"
DISPATCH_CONFIG_TOML = (
    'approval_policy = "never"\n'
    'sandbox_mode = "danger-full-access"\n'
    "hide_agent_reasoning = true\n"
)


async def maybe_send_failure_alert(*, http_client: AsyncClient, settings: RegistrySettings, msg: str) -> None:
    """Keep the existing enable/token/recipient admission and chunked transport."""
    if not settings.alerts_enabled:
        return
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        LOGGER.warning("Telegram not configured; skipping alert")
        return
    config = TelegramConfig(bot_token=settings.telegram_bot_token, chat_id=settings.telegram_chat_id)
    ok_all, _responses = await send_telegram_message_chunked(http_client, config, msg)
    LOGGER.info("Telegram alert sent ok=%s", ok_all)


async def maybe_dispatch_failure_investigation(
    *, http_client: AsyncClient, settings: RegistrySettings, prompt: str, context: JsonObject | None = None,
) -> None:
    """Retain dispatch admission, status/log reads, DB persistence and notice order."""
    if not settings.dispatch_enabled:
        return
    if not settings.dispatch_token:
        LOGGER.warning("Dispatcher token missing; skipping dispatch")
        return
    config = DispatchConfig(
        base_url=settings.dispatch_base_url, token=settings.dispatch_token, model=settings.dispatch_model or None,
        poll_interval_seconds=5.0, max_wait_seconds=20 * 60, log_tail_bytes=250_000,
    )
    bundle, _runner = await dispatch_job(
        http_client, config, prompt=prompt, config_toml=DISPATCH_CONFIG_TOML, state_key=DISPATCH_STATE_KEY,
    )
    status = cast("JsonObject", await wait_for_terminal_status(http_client, config, bundle=bundle))
    queue_state = str(status.get("queue_state") or "")
    ui = run_ui_url(config.base_url, bundle)
    tail = await get_run_log_tail(http_client, config, bundle=bundle)
    message = extract_last_agent_message_from_exec_log(tail)
    error = None
    if message:
        LOGGER.info("Dispatch completed state=%s ui=%s last_msg=%s", queue_state, ui, message[:200])
    elif queue_state != "processed":
        error = extract_last_error_message_from_exec_log(tail) or ""
    else:
        error = "no_agent_message"
    record = DispatchRecord(DISPATCH_STATE_KEY, bundle, ui, queue_state, message, error)
    await record.persist(settings, context)
    notice = record.notice()
    if notice is not None:
        await maybe_send_failure_alert(http_client=http_client, settings=settings, msg=notice)
