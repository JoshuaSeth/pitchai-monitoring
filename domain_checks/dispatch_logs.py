# Copyright (c) 2026 PitchAI. All rights reserved.
"""Bounded Dispatcher log retrieval and terminal-message extraction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain_checks.dispatch_http import (
    DISPATCH_TIMEOUT_SECONDS,
    READ_TIMEOUT_SECONDS,
    decode_json_object,
)
from domain_checks.dispatch_models import (
    extract_last_agent_message_from_exec_log,
    extract_last_error_message_from_exec_log,
)

if TYPE_CHECKING:
    import httpx

    from domain_checks.dispatch_models import DispatchConfig

_MAX_LOG_TAIL_BYTES = 5_000_000


async def get_run_log_tail(
    client: httpx.AsyncClient,
    config: DispatchConfig,
    *,
    bundle: str,
) -> str:
    """Return the configured tail of a Dispatcher run log."""
    url = f"{config.base_url.rstrip('/')}/runs/{bundle}/log"
    headers = {"X-PitchAI-Dispatch-Token": config.token}
    head = await client.get(
        url,
        headers=headers,
        params={"offset": 0, "max_bytes": 1},
        timeout=READ_TIMEOUT_SECONDS,
    )
    _ = head.raise_for_status()
    metadata = decode_json_object(head, response_name="log metadata")
    if metadata.get("exists") is not True:
        return ""
    raw_size = metadata.get("size")
    size = int(raw_size) if isinstance(raw_size, int | float | str) and not isinstance(raw_size, bool) else 0
    bounded_bytes = max(1, min(config.log_tail_bytes, _MAX_LOG_TAIL_BYTES))
    tail = await client.get(
        url,
        headers=headers,
        params={"offset": max(0, size - bounded_bytes), "max_bytes": bounded_bytes},
        timeout=DISPATCH_TIMEOUT_SECONDS,
    )
    _ = tail.raise_for_status()
    payload = decode_json_object(tail, response_name="log tail")
    content = payload.get("content")
    return content if isinstance(content, str) else ""


async def get_last_agent_message(
    client: httpx.AsyncClient,
    config: DispatchConfig,
    *,
    bundle: str,
) -> str | None:
    """Return the latest agent message from a Dispatcher run."""
    tail = await get_run_log_tail(client, config, bundle=bundle)
    return extract_last_agent_message_from_exec_log(tail)


async def get_last_error_message(
    client: httpx.AsyncClient,
    config: DispatchConfig,
    *,
    bundle: str,
) -> str | None:
    """Return the latest error message from a Dispatcher run."""
    tail = await get_run_log_tail(client, config, bundle=bundle)
    return extract_last_error_message_from_exec_log(tail)
