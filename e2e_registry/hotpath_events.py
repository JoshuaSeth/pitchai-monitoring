# Copyright (c) 2026 PitchAI. All rights reserved.
"""Leased, at-least-once Events Bus delivery for hotpath incident intents."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from contextlib import closing
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from .hotpath_codec import canonical_json, decode_object
from .hotpath_event_bus_runtime import load_event_bus_config
from .hotpath_event_gateway import EventWork, deliver_event
from .hotpath_store_schema import (
    connect,
    ensure_schema,
    row_float,
    row_integer,
    row_optional_string,
    row_string,
)

if TYPE_CHECKING:
    import sqlite3

    from .hotpath_event_bus_runtime import EventBusConfig
    from .hotpath_types import JsonValue

LOGGER = logging.getLogger("e2e-registry.hotpaths")
_DELIVERY_LEASE_SECONDS = 60.0
_IDLE_POLL_SECONDS = 2.0
_MAX_RETRY_SECONDS = 300.0
_MAX_RETRY_EXPONENT = 8
_MAX_ERROR_LENGTH = 240
_EVENT_KINDS = frozenset({"hotpath_red", "hotpath_recovered"})


class HotpathEventError(ValueError):
    """A persisted event intent violates the typed producer contract."""


async def run_event_worker(db_path: str, stop: asyncio.Event) -> None:
    """Deliver due incident intents until application shutdown."""
    config = load_event_bus_config()
    if config is None:
        LOGGER.warning("Hotpath Events Bus intents will remain pending: delivery is not configured")
        return
    while not stop.is_set():
        work = await asyncio.to_thread(_claim_due, db_path, config, time.time())
        if work is None:
            await asyncio.sleep(_IDLE_POLL_SECONDS)
            continue
        await _deliver_claimed(db_path, config, work)


async def _deliver_claimed(db_path: str, config: EventBusConfig, work: EventWork) -> None:
    now_ts = time.time()
    results = await asyncio.gather(deliver_event(config, work, now_ts=now_ts), return_exceptions=True)
    result = results[0]
    if isinstance(result, BaseException):
        await asyncio.to_thread(_record_failure, db_path, work.intent_id, type(result).__name__, now_ts)
    elif result.event_id is not None:
        await asyncio.to_thread(_record_success, db_path, work.intent_id, result.event_id, now_ts)
    else:
        await asyncio.to_thread(_record_failure, db_path, work.intent_id, result.error or "delivery_failed", now_ts)


def _claim_due(db_path: str, config: EventBusConfig, now_ts: float) -> EventWork | None:
    ensure_schema(db_path)
    with closing(connect(db_path)) as connection:
        _ = connection.execute("BEGIN IMMEDIATE")
        row = cast(
            "sqlite3.Row | None",
            connection.execute(
                """SELECT intent_id, event_kind, occurred_at_ts, details_json, delivery_entry_json
                FROM hotpath_event_outbox
                WHERE status IN ('pending', 'retrying', 'delivering') AND next_attempt_at_ts <= ?
                ORDER BY created_at_ts LIMIT 1""",
                (now_ts,),
            ).fetchone(),
        )
        if row is None:
            _ = connection.execute("COMMIT")
            return None
        work = _event_work(row, config)
        _ = connection.execute(
            """UPDATE hotpath_event_outbox SET status = 'delivering', delivery_entry_json = ?,
            next_attempt_at_ts = ?, updated_at_ts = ? WHERE intent_id = ?""",
            (work.payload_json, now_ts + _DELIVERY_LEASE_SECONDS, now_ts, work.intent_id),
        )
        _ = connection.execute("COMMIT")
        return work


def _event_work(row: sqlite3.Row, config: EventBusConfig) -> EventWork:
    intent_id = row_string(row, "intent_id")
    event_kind = row_string(row, "event_kind")
    payload_json = row_optional_string(row, "delivery_entry_json")
    if payload_json is None:
        payload = _build_payload(
            config,
            event_kind,
            row_float(row, "occurred_at_ts"),
            decode_object(row_string(row, "details_json")),
        )
        payload_json = canonical_json(payload)
    payload = decode_object(payload_json)
    delivery_id = payload.get("delivery_id")
    if not isinstance(delivery_id, str) or not delivery_id:
        error = "delivery_id"
        raise HotpathEventError(error)
    return EventWork(intent_id, event_kind, delivery_id, payload_json)


def _build_payload(
    config: EventBusConfig,
    event_kind: str,
    occurred_at_ts: float,
    details: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    if event_kind not in _EVENT_KINDS:
        raise HotpathEventError(event_kind)
    source: dict[str, JsonValue] = {
        "environment": config.environment,
        "instance": config.instance,
        "service": "service-monitoring",
    }
    if config.deployment_sha:
        source["deployment_sha"] = config.deployment_sha
    payload: dict[str, JsonValue] = {
        "details": details,
        "event_kind": event_kind,
        "occurred_at": datetime
        .fromtimestamp(occurred_at_ts, tz=UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        "schema_version": 1,
        "source": source,
    }
    digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    payload["delivery_id"] = f"monitoring-{digest}"
    return payload


def _record_success(db_path: str, intent_id: str, event_id: str, now_ts: float) -> None:
    with closing(connect(db_path)) as connection:
        _ = connection.execute(
            """UPDATE hotpath_event_outbox SET status = 'delivered', receiver_event_id = ?,
            next_attempt_at_ts = 0, last_error = NULL, updated_at_ts = ? WHERE intent_id = ?""",
            (event_id, now_ts, intent_id),
        )


def _record_failure(db_path: str, intent_id: str, error: str, now_ts: float) -> None:
    with closing(connect(db_path)) as connection:
        row = cast(
            "sqlite3.Row | None",
            connection.execute(
                "SELECT attempts FROM hotpath_event_outbox WHERE intent_id = ?",
                (intent_id,),
            ).fetchone(),
        )
        attempts = (row_integer(row, "attempts") if row is not None else 0) + 1
        retry_at = now_ts + min(_MAX_RETRY_SECONDS, 2.0 ** min(attempts, _MAX_RETRY_EXPONENT))
        _ = connection.execute(
            """UPDATE hotpath_event_outbox SET status = 'retrying', attempts = ?, next_attempt_at_ts = ?,
            last_error = ?, updated_at_ts = ? WHERE intent_id = ?""",
            (attempts, retry_at, error[:_MAX_ERROR_LENGTH], now_ts, intent_id),
        )
