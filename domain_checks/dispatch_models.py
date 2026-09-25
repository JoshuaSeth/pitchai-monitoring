# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed Dispatcher contracts and log parsing for domain monitoring."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast

if TYPE_CHECKING:
    from domain_checks.types import JsonObject, JsonValue


class DispatchRunStatus(TypedDict, total=False):
    """Represent the dispatcher fields used while polling a run."""

    queue_state: str | None
    runner_status: str | None
    thread_id: str | None
    live_status: JsonValue
    record: JsonObject


class DispatchJobOptions(TypedDict):
    """Keyword options accepted by a Dispatcher submission."""

    prompt: str
    config_toml: str
    state_key: NotRequired[str | None]
    pre_commands: NotRequired[list[str] | None]


@dataclass(frozen=True)
class DispatchConfig:
    """Configure Dispatcher submission and polling."""

    base_url: str
    token: str
    model: str | None = None
    poll_interval_seconds: float = 5.0
    max_wait_seconds: float = 20 * 60
    log_tail_bytes: int = 250_000


def parse_dispatch_response(text: str) -> tuple[str, str]:
    """Parse ``queued:<bundle>:runner:<runner>`` from Dispatcher.

    Returns:
        The bundle and runner identifiers.

    Raises:
        ValueError: The response does not match the queued-job contract.
    """
    response = (text or "").strip()
    if not response.startswith("queued:"):
        message = f"Unexpected dispatch response: {response!r}"
        raise ValueError(message)
    remainder = response[len("queued:") :]
    if ":runner:" not in remainder:
        message = f"Unexpected dispatch response: {response!r}"
        raise ValueError(message)
    bundle, runner = remainder.split(":runner:", 1)
    cleaned_bundle = bundle.strip()
    if not cleaned_bundle:
        message = f"Unexpected dispatch response: {response!r}"
        raise ValueError(message)
    return cleaned_bundle, runner.strip()


def _decoded_log_line(line: str) -> JsonObject | None:
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None
    try:
        value = cast("JsonValue", json.loads(stripped))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def extract_last_agent_message_from_exec_log(text: str) -> str | None:
    """Return the latest agent-message item from a Dispatcher exec log."""
    for line in reversed((text or "").splitlines()):
        item = _decoded_log_line(line)
        if item is None or item.get("type") not in {"item.completed", "item.updated"}:
            continue
        payload = item.get("item")
        if not isinstance(payload, dict) or payload.get("type") != "agent_message":
            continue
        message = payload.get("text")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return None


def extract_last_error_message_from_exec_log(text: str) -> str | None:
    """Return the latest terminal error from a Dispatcher exec log."""
    for line in reversed((text or "").splitlines()):
        item = _decoded_log_line(line)
        if item is None:
            continue
        event_type = item.get("type")
        if event_type == "error":
            message = item.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        if event_type != "turn.failed":
            continue
        error = item.get("error")
        if not isinstance(error, dict):
            continue
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return None


def run_ui_url(base_url: str, bundle: str) -> str:
    """Return the human-facing Dispatcher run URL."""
    root = base_url.rstrip("/")
    run_path = f"/ui/runs/{bundle}"
    return f"{root}{run_path}"
