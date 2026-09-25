# Copyright (c) 2026 PitchAI. All rights reserved.
"""Persisted incident-triage conclusions for the monitoring dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from e2e_registry.db_core import fetch_all_rows, new_uuid, rows_records, utc_timestamp
from e2e_registry.db_schema import registry_connection
from e2e_registry.models import (
    InvalidRegistryDataError,
    dump_json,
    parse_json_object,
)

if TYPE_CHECKING:
    from e2e_registry.models import (
        JsonObject,
        JsonValue,
    )
    from e2e_registry.settings import RegistrySettings

_MAX_DISPATCH_RUNS = 500
_MAX_AGENT_MESSAGE_LENGTH = 20_000
_MAX_ERROR_MESSAGE_LENGTH = 5_000


@dataclass(frozen=True)
class DispatchRunEntry:
    """One dispatcher-triage conclusion to persist."""

    state_key: str
    bundle: str | None
    ui_url: str | None
    queue_state: str | None
    agent_message: str | None
    error_message: str | None
    context: JsonObject | None = None


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def insert_dispatch_run(
    settings: RegistrySettings,
    entry: DispatchRunEntry,
) -> JsonObject:
    """Persist and return one incident-triage conclusion.

    Returns:
        The stored conclusion with its generated identity and timestamp.
    """
    run_id = new_uuid()
    now = utc_timestamp()
    bundle = _optional_text(entry.bundle)
    ui_url = _optional_text(entry.ui_url)
    queue_state = _optional_text(entry.queue_state)
    agent_message = _optional_text(entry.agent_message)
    error_message = _optional_text(entry.error_message)
    context = entry.context if entry.context is not None else {}
    if agent_message is not None:
        agent_message = agent_message[:_MAX_AGENT_MESSAGE_LENGTH]
    if error_message is not None:
        error_message = error_message[:_MAX_ERROR_MESSAGE_LENGTH]

    with registry_connection(settings) as connection:
        connection.execute(
            """
            INSERT INTO dispatch_runs (
              id, created_at_ts, state_key, bundle, ui_url, queue_state, agent_message, error_message, context_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                now,
                entry.state_key.strip(),
                bundle,
                ui_url,
                queue_state,
                agent_message,
                error_message,
                dump_json(context),
            ),
        )
    return {
        "id": run_id,
        "created_at_ts": now,
        "state_key": entry.state_key,
        "bundle": bundle,
        "ui_url": ui_url,
        "queue_state": queue_state,
        "agent_message": agent_message,
        "error_message": error_message,
        "context": context,
    }


def _dispatch_json_record(
    record: dict[str, str | int | float | bytes | None],
) -> JsonObject:
    output: JsonObject = {}
    for key, value in record.items():
        if key == "context_json":
            output["context"] = parse_json_object(
                value,
                label="dispatch context",
                empty_when_missing=True,
            )
        elif isinstance(value, bytes):
            message = f"Dispatch field {key} unexpectedly contains bytes"
            raise InvalidRegistryDataError(message)
        else:
            json_value: JsonValue = value
            output[key] = json_value
    return output


def list_dispatch_runs(
    settings: RegistrySettings,
    *,
    limit: int = 80,
) -> list[JsonObject]:
    """Return recent dispatcher-triage conclusions."""
    bounded_limit = max(1, min(limit, _MAX_DISPATCH_RUNS))
    with registry_connection(settings) as connection:
        rows = fetch_all_rows(
            connection.execute(
                """
            SELECT id, created_at_ts, state_key, bundle, ui_url, queue_state,
                   agent_message, error_message, context_json
            FROM dispatch_runs
            ORDER BY created_at_ts DESC
            LIMIT ?
            """,
                (bounded_limit,),
            ),
        )
        records = rows_records(rows)
        return [_dispatch_json_record(record) for record in records]
