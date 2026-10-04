# Copyright (c) 2026 PitchAI. All rights reserved.
"""Leased delivery of original registry results through the signed Events Bus."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from httpx import HTTPError

from domain_checks.event_bus import load_event_bus_config
from domain_checks.event_bus_delivery import build_incident_payload, deliver_event_bus_payload

from .hotpath_codec import canonical_json, decode_object
from .hotpath_store_schema import connect, row_integer, row_optional_string, row_string

if TYPE_CHECKING:
    import sqlite3

    from httpx import BaseTransport

    from domain_checks.event_bus import EventBusConfig

LOGGER = logging.getLogger("e2e-registry.completions")
EVENT_KIND = "registry_run_complete"
_LEASE_SECONDS = 120.0
_RETRY_SECONDS = 30.0


@dataclass(frozen=True)
class CompletionDelivery:
    """An immutable source obligation with its current exclusive lease."""

    run_id: str
    lease_token: str
    payload_json: str
    attempt: int


def claim_completion(db_path: str, config: EventBusConfig, *, now: float) -> CompletionDelivery | None:
    """Persist payload identity before network I/O and recover expired claims.

    Returns:
        One leased original result, or no currently due obligation.
    """
    with closing(connect(db_path)) as connection, connection as transaction:
        due = cast("sqlite3.Row | None", connection.execute(
            """SELECT run_id FROM registry_completion_outbox
            WHERE receiver_event_id IS NULL AND next_attempt_at <= ? LIMIT 1""", (now,),
        ).fetchone())
        if due is None:
            return None
        _ = transaction.execute("BEGIN IMMEDIATE")
        row = cast("sqlite3.Row | None", connection.execute(
            """SELECT * FROM registry_completion_outbox
            WHERE receiver_event_id IS NULL AND next_attempt_at <= ?
            ORDER BY captured_at, run_id LIMIT 1""", (now,),
        ).fetchone())
        if row is None:
            return None
        payload_json = row_optional_string(row, "delivery_json")
        if payload_json is None:
            payload = build_incident_payload(
                config, kind=EVENT_KIND,
                occurred_at=datetime.fromisoformat(row_string(row, "captured_at")).timestamp(),
                details=decode_object(row_string(row, "body_json")),
            )
            payload_json = canonical_json(payload)
        lease_token = str(uuid4())
        run_id = row_string(row, "run_id")
        attempt = row_integer(row, "attempts") + 1
        _ = connection.execute(
            """UPDATE registry_completion_outbox SET delivery_json=?, lease_token=?,
            next_attempt_at=?, attempts=? WHERE run_id=?""",
            (payload_json, lease_token, now + _LEASE_SECONDS, attempt, run_id),
        )
        return CompletionDelivery(run_id, lease_token, payload_json, attempt)


def record_completion_receipt(
    db_path: str, work: CompletionDelivery, *, event_id: str | None, error: str | None, now: float,
) -> bool:
    """Settle only the current lease; a lost ACK retries the same payload identity.

    Returns:
        Whether this receipt still owned its original lease.

    Raises:
        ValueError: A receipt is neither a nonempty acceptance nor an error.
    """
    if (event_id is None and not error) or (event_id is not None and (not event_id or error is not None)):
        message = "Completion delivery requires exactly one acceptance or failure."
        raise ValueError(message)
    retry_at = 0.0 if event_id else now + _RETRY_SECONDS
    with closing(connect(db_path)) as connection:
        result = connection.execute(
            """UPDATE registry_completion_outbox SET receiver_event_id=?, last_error=?,
            next_attempt_at=?, lease_token=NULL
            WHERE run_id=? AND lease_token=? AND receiver_event_id IS NULL""",
            (event_id, error, retry_at, work.run_id, work.lease_token),
        )
        return result.rowcount == 1


async def deliver_completion(
    db_path: str, config: EventBusConfig, work: CompletionDelivery, *, transport: BaseTransport | None = None,
) -> bool:
    """Use the existing authenticated gateway without holding a database lock.

    Returns:
        Whether the current receipt was durably recorded, not manager consumption.
    """
    event_id: str | None = None
    error: str | None = None
    payload = decode_object(work.payload_json)
    results = await asyncio.gather(
        asyncio.to_thread(deliver_event_bus_payload, config, payload, transport=transport), return_exceptions=True,
    )
    result = results[0]
    if isinstance(result, (HTTPError, OSError, ValueError, TypeError)):
        # Store the category only; transport exception strings can contain URLs.
        error = type(result).__name__
    elif isinstance(result, BaseException):
        raise result
    elif result.delivery_id != payload.get("delivery_id"):
        error = "delivery_identity_mismatch"
    elif result.success and result.event_id:
        event_id = result.event_id
    else:
        error = result.error or "missing_receiver_acceptance"
    return await asyncio.to_thread(
        record_completion_receipt, db_path, work, event_id=event_id, error=error, now=time.time(),
    )


async def run_completion_worker(db_path: str, stop: asyncio.Event) -> None:
    """Drain original durable results; receiver outages retain every obligation."""
    config = load_event_bus_config()
    if config is None:
        LOGGER.warning("Registry completions remain pending: signed Events Bus delivery is not configured")
        return
    while not stop.is_set():
        work = await asyncio.to_thread(claim_completion, db_path, config, now=time.time())
        if work is not None:
            _ = await deliver_completion(db_path, config, work)
            continue
        await asyncio.sleep(2.0)
