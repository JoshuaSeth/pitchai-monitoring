# Copyright (c) 2026 PitchAI. All rights reserved.
"""HTTP gateway for domain-monitor Dispatcher integration."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Unpack

import httpx

from domain_checks.dispatch_http import (
    DISPATCH_TIMEOUT_SECONDS,
    READ_TIMEOUT_SECONDS,
    decode_json_object,
)
from domain_checks.dispatch_logs import (
    get_last_agent_message,
    get_last_error_message,
    get_run_log_tail,
)
from domain_checks.dispatch_models import (
    DispatchRunStatus,
    parse_dispatch_response,
)

__all__ = [
    "dispatch_job",
    "get_last_agent_message",
    "get_last_error_message",
    "get_run_log_tail",
    "get_run_record",
    "get_run_status",
    "wait_for_terminal_status",
]

if TYPE_CHECKING:
    from domain_checks.dispatch_models import (
        DispatchConfig,
        DispatchJobOptions,
    )
    from domain_checks.types import JsonObject

_NOT_FOUND_STATUS_CODE = 404
_TERMINAL_QUEUE_STATES = frozenset({"processed", "failed", "runner_error"})
_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


async def dispatch_job(
    client: httpx.AsyncClient,
    config: DispatchConfig,
    **options: Unpack[DispatchJobOptions],
) -> tuple[str, str]:
    """Submit one Dispatcher job and return its bundle and runner values.

    Returns:
        The submitted job's bundle and runner identifiers.
    """
    payload: JsonObject = {
        "prompt": options["prompt"],
        "config_toml": options["config_toml"],
    }
    if config.model:
        payload["model"] = config.model
    state_key = options.get("state_key")
    if state_key:
        payload["state_key"] = state_key
    pre_commands = options.get("pre_commands")
    if pre_commands:
        payload["pre_commands"] = pre_commands
    response = await client.post(
        f"{config.base_url.rstrip('/')}/dispatch",
        headers={"X-PitchAI-Dispatch-Token": config.token},
        json=payload,
        timeout=DISPATCH_TIMEOUT_SECONDS,
    )
    _ = response.raise_for_status()
    return parse_dispatch_response(response.text)


def _optional_text(data: JsonObject, key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) else None


def _run_status_from_json(data: JsonObject) -> DispatchRunStatus:
    status = DispatchRunStatus(
        queue_state=_optional_text(data, "queue_state"),
        runner_status=_optional_text(data, "runner_status"),
        thread_id=_optional_text(data, "thread_id"),
    )
    if "live_status" in data:
        status["live_status"] = data["live_status"]
    record = data.get("record")
    if isinstance(record, dict):
        status["record"] = record
    return status


async def get_run_status(
    client: httpx.AsyncClient,
    config: DispatchConfig,
    *,
    bundle: str,
) -> DispatchRunStatus:
    """Read a Dispatcher run's live status.

    Returns:
        The decoded live run status.
    """
    response = await client.get(
        f"{config.base_url.rstrip('/')}/runs/{bundle}/status",
        headers={"X-PitchAI-Dispatch-Token": config.token},
        timeout=READ_TIMEOUT_SECONDS,
    )
    _ = response.raise_for_status()
    return _run_status_from_json(decode_json_object(response, response_name="status"))


async def get_run_record(
    client: httpx.AsyncClient,
    config: DispatchConfig,
    *,
    bundle: str,
) -> JsonObject:
    """Read a persisted Dispatcher run record.

    Returns:
        The decoded persisted run record.
    """
    response = await client.get(
        f"{config.base_url.rstrip('/')}/runs/{bundle}/record",
        headers={"X-PitchAI-Dispatch-Token": config.token},
        timeout=READ_TIMEOUT_SECONDS,
    )
    _ = response.raise_for_status()
    return decode_json_object(response, response_name="record")


async def _get_status_or_record(
    client: httpx.AsyncClient,
    config: DispatchConfig,
    *,
    bundle: str,
) -> DispatchRunStatus:
    try:
        return await get_run_status(client, config, bundle=bundle)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != _NOT_FOUND_STATUS_CODE:
            raise
    record = await get_run_record(client, config, bundle=bundle)
    return DispatchRunStatus(
        queue_state=_optional_text(record, "status"),
        record=record,
    )


def _is_transient_dispatch_error(exc: httpx.HTTPError | TypeError | ValueError) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _TRANSIENT_STATUS_CODES
    return False


async def wait_for_terminal_status(
    client: httpx.AsyncClient,
    config: DispatchConfig,
    *,
    bundle: str,
) -> DispatchRunStatus:
    """Poll until Dispatcher reaches a terminal queue state.

    Returns:
        The terminal Dispatcher status.

    Raises:
        HTTPError: Dispatcher returns a terminal HTTP failure.
        TimeoutError: Dispatcher does not finish before the configured deadline.
        TypeError: Dispatcher returns a response with an invalid type.
        ValueError: Dispatcher returns malformed JSON or an invalid value.
    """
    deadline = time.monotonic() + max(1.0, config.max_wait_seconds)
    while True:
        try:
            status = await _get_status_or_record(client, config, bundle=bundle)
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            if not _is_transient_dispatch_error(exc) or time.monotonic() >= deadline:
                raise
            await asyncio.sleep(max(0.5, config.poll_interval_seconds))
            continue
        if status.get("queue_state") in _TERMINAL_QUEUE_STATES:
            return status
        if time.monotonic() >= deadline:
            message = f"Timed out waiting for dispatcher run to finish (bundle={bundle})"
            raise TimeoutError(message)
        await asyncio.sleep(max(0.5, config.poll_interval_seconds))
