# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed observation boundary around the existing dispatch/forward operation."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Unpack, cast

from httpx import HTTPStatusError

from .dispatch_client import (
    dispatch_job,
    extract_last_agent_message_from_exec_log,
    extract_last_error_message_from_exec_log,
    get_last_agent_message,
    get_run_log_tail,
    run_ui_url,
    wait_for_terminal_status,
)
from .dispatch_context import DispatchRequest, DispatchRun, DispatchRuntime
from .dispatch_errors import handle_error, handle_http_error
from .dispatch_result import complete_message, complete_without_message
from .dispatch_runner_config import CODEX_CONFIG_TOML, DOCKER_CLI_INSTALL_PRE_COMMAND
from .dispatch_state import dispatch_is_enabled

if TYPE_CHECKING:
    from .dispatch_context import PromptInputs
    from .event_bus_delivery import JsonObject

LOGGER = logging.getLogger("service-monitoring")


async def dispatch_prompt_and_forward(**inputs: Unpack[PromptInputs]) -> None:
    """Construct the existing request and observe its transport lifecycle."""
    runtime = DispatchRuntime.from_inputs(inputs)
    request = DispatchRequest(inputs["prompt"], inputs["state_key"], inputs["telegram_title"])
    await run_dispatch(runtime, request)


async def run_dispatch(runtime: DispatchRuntime, request: DispatchRequest) -> None:
    """Handle ordinary failures explicitly; propagate cancellation and fatal signals."""
    if not dispatch_is_enabled(runtime.config, runtime.state):
        LOGGER.info("Dispatch disabled; skipping dispatch title=%s", request.title)
        return
    # Gather observes this one I/O workflow's result. Parent cancellation still
    # cancels it; a cancelled child must never become a completion record.
    operation = asyncio.create_task(execute_dispatch(runtime, request))
    outcomes = await asyncio.gather(operation, return_exceptions=True)
    if operation.cancelled():
        # Await the task itself to retain its original cancellation exception;
        # gather's returned cancellation does not preserve the child's message.
        await operation
    outcome = outcomes[0]
    if isinstance(outcome, HTTPStatusError):
        await handle_http_error(runtime, request, outcome)
    elif isinstance(outcome, Exception):
        await handle_error(runtime, request, outcome)
    elif isinstance(outcome, BaseException):
        raise outcome


async def execute_dispatch(runtime: DispatchRuntime, request: DispatchRequest) -> None:
    """Queue, await and forward through the same existing client operations."""
    started = time.time()
    bundle, runner = await dispatch_job(
        runtime.client, runtime.config, prompt=request.prompt, config_toml=CODEX_CONFIG_TOML,
        state_key=request.state_key, pre_commands=[DOCKER_CLI_INSTALL_PRE_COMMAND],
    )
    LOGGER.info("Dispatch queued title=%s bundle=%s runner=%s", request.title, bundle, runner)
    status = cast("JsonObject", await wait_for_terminal_status(runtime.client, runtime.config, bundle=bundle))
    queue_state = str(status.get("queue_state") or "")
    ui = run_ui_url(runtime.config.base_url, bundle)
    run = DispatchRun(started, bundle, runner, queue_state, ui)
    tail = await get_run_log_tail(runtime.client, runtime.config, bundle=bundle)
    message = extract_last_agent_message_from_exec_log(tail) or await get_last_agent_message(
        runtime.client, runtime.config, bundle=bundle,
    )
    if message:
        await complete_message(runtime, request, run, message)
    else:
        error = extract_last_error_message_from_exec_log(tail) or ""
        await complete_without_message(runtime, request, run, error)
