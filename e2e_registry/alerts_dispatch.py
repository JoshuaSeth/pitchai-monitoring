# Copyright (c) 2026 PitchAI. All rights reserved.
"""Optional external failure-triage dispatch and persistence."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import TYPE_CHECKING

from domain_checks.dispatch_client import (
    DispatchConfig,
    dispatch_job,
    extract_last_agent_message_from_exec_log,
    extract_last_error_message_from_exec_log,
    get_run_log_tail,
    run_ui_url,
    wait_for_terminal_status,
)
from e2e_registry import db as dbm
from e2e_registry.alerts import maybe_send_failure_alert

if TYPE_CHECKING:
    import httpx

    from e2e_registry.models import JsonObject
    from e2e_registry.settings import RegistrySettings

LOGGER = logging.getLogger("e2e-registry")
_STATE_KEY = "e2e-registry.failure"
_DISPATCH_CONFIGURATION = (
    'approval_policy = "never"\n'
    'sandbox_mode = "danger-full-access"\n'
    "hide_agent_reasoning = true\n"
)


async def _persist_dispatch_run(
    *,
    settings: RegistrySettings,
    entry: dbm.DispatchRunEntry,
) -> None:
    try:
        await asyncio.to_thread(dbm.insert_dispatch_run, settings, entry)
    except (OSError, sqlite3.Error):
        LOGGER.exception("Failed to persist dispatch run record")


def _dispatch_config(settings: RegistrySettings) -> DispatchConfig:
    return DispatchConfig(
        base_url=settings.dispatch_base_url,
        token=settings.dispatch_token,
        model=settings.dispatch_model or None,
        poll_interval_seconds=5.0,
        max_wait_seconds=20 * 60,
        log_tail_bytes=250_000,
    )


async def maybe_dispatch_failure_investigation(
    *,
    http_client: httpx.AsyncClient,
    settings: RegistrySettings,
    prompt: str,
    context: JsonObject | None = None,
) -> None:
    """Dispatch optional read-only triage and persist its terminal conclusion."""
    if not settings.dispatch_enabled:
        return
    if not settings.dispatch_token:
        LOGGER.warning("Dispatcher token missing; skipping dispatch")
        return
    config = _dispatch_config(settings)
    bundle, _runner = await dispatch_job(
        http_client,
        config,
        prompt=prompt,
        config_toml=_DISPATCH_CONFIGURATION,
        state_key=_STATE_KEY,
    )
    status = await wait_for_terminal_status(http_client, config, bundle=bundle)
    queue_state = str(status.get("queue_state") or "")
    ui_url = run_ui_url(config.base_url, bundle)
    log_tail = await get_run_log_tail(http_client, config, bundle=bundle)
    agent_message = extract_last_agent_message_from_exec_log(log_tail)
    normalized_context = context or {}
    if agent_message:
        LOGGER.info(
            "Dispatch completed state=%s ui=%s last_msg=%s",
            queue_state,
            ui_url,
            agent_message[:200],
        )
        await _persist_dispatch_run(
            settings=settings,
            entry=dbm.DispatchRunEntry(
                state_key=_STATE_KEY,
                bundle=bundle,
                ui_url=ui_url,
                queue_state=queue_state,
                agent_message=agent_message,
                error_message=None,
                context=normalized_context,
            ),
        )
        await maybe_send_failure_alert(
            http_client=http_client,
            settings=settings,
            msg=f"Dispatcher triage completed:\n{ui_url}\n\n{agent_message}".strip(),
        )
        return
    error_message = (
        extract_last_error_message_from_exec_log(log_tail) or ""
        if queue_state != "processed"
        else "no_agent_message"
    )
    await _persist_dispatch_run(
        settings=settings,
        entry=dbm.DispatchRunEntry(
            state_key=_STATE_KEY,
            bundle=bundle,
            ui_url=ui_url,
            queue_state=queue_state,
            agent_message=None,
            error_message=error_message,
            context=normalized_context,
        ),
    )
    if queue_state != "processed":
        await maybe_send_failure_alert(
            http_client=http_client,
            settings=settings,
            msg=f"Dispatcher triage failed state={queue_state} ui={ui_url}\nError: {error_message[:500]}",
        )
