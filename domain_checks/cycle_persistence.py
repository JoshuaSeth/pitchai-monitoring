# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing snapshot, event and outbox persistence owned by the native cycle."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Self, cast

from .browser_state import browser_state_snapshot
from .event_bus import EventBusOutbox
from .state_storage import write_state_atomic

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path
    from types import TracebackType

    from httpx import AsyncClient

    from .browser_admission import BrowserStateValue
    from .cycle_health_state import CycleHealthState
    from .cycle_records import CycleRecords
    from .dft_cycle import DftCycle
    from .event_bus import EventBusConfig
    from .event_bus_delivery import JsonObject, JsonValue

LOGGER = logging.getLogger("service-monitoring")
type WriteReason = Literal["event", "browser_notice", "cycle", "post_meta"]
_WRITE_MESSAGES: dict[WriteReason, str] = {
    "event": "Failed to persist PitchAI Events Bus outbox path=%s error=%s",
    "browser_notice": "Failed to persist degraded notice timestamp path=%s error=%s",
    "cycle": "Failed to write state file path=%s error=%s",
    "post_meta": "Failed to write post-meta state file path=%s error=%s",
}
_EVENT_LIMIT = 10_000
_EVENT_RETAINED = 8000


class InvalidOutboxStateError(TypeError, RuntimeError):
    """Invalid queue type, retaining compatibility with existing RuntimeError callers."""


def restore_outbox(config: EventBusConfig | None, disk: Mapping[str, JsonValue]) -> EventBusOutbox | None:
    """Restore the existing queue, leaving entry validation to its native constructor.

    Returns:
        The same enabled queue or None when delivery is unconfigured.

    Raises:
        InvalidOutboxStateError: Persisted outbox state is not a list.
    """
    if config is None:
        return None
    raw = disk.get("event_bus_outbox", [])
    if not isinstance(raw, list):
        message = "Persisted PitchAI Events Bus outbox must be a list"
        raise InvalidOutboxStateError(message)
    # The constructor validates each decoded JSON entry, including invalid scalars.
    outbox = EventBusOutbox(config, entries=cast("list[JsonObject]", raw))
    LOGGER.info("Loaded PitchAI Events Bus outbox pending=%s", outbox.pending_count)
    return outbox


@dataclass(frozen=True)
class _WriteBoundary:
    """Count ordinary write failures; cancellation and process exits stay loud."""

    path: Path
    health: CycleHealthState
    reason: WriteReason

    def __enter__(self) -> Self:
        return self

    def __exit__(self, _kind: type[BaseException] | None, error: BaseException | None,
                 _traceback: TracebackType | None) -> bool:
        if error is None:
            self.health.write_fail_streak = 0
            return False
        if not isinstance(error, Exception):
            return False
        self.health.write_fail_streak = int(self.health.write_fail_streak) + 1
        LOGGER.warning(_WRITE_MESSAGES[self.reason], self.path, error)
        return True


@dataclass(frozen=True)
class CyclePersistence:
    """Use the existing state file and outbox, without allocating a journal or route."""

    path: Path | None
    records: CycleRecords
    health: CycleHealthState
    browser: Mapping[str, BrowserStateValue]
    dft: DftCycle
    outbox: EventBusOutbox | None

    def snapshot(self) -> JsonObject:
        """Return the original schema-six state with live record aliases and capped lists."""
        queued = cast("list[JsonValue]", self.outbox.to_state()) if self.outbox else []
        return {
            "version": 6,
            "history_ok_mode": "effective",
            "updated_at": datetime.now(UTC).isoformat(),
            **self.records.snapshot(),
            "event_bus_outbox": queued,
            "dft_web_access": self.dft.summary,
            "host_last_snapshot": self.health.host.last_snapshot,
            **browser_state_snapshot(self.browser),
            **self.health.snapshot(self.health.write_fail_streak),
        }

    def persist(self, reason: WriteReason) -> None:
        """Keep each original warning and update the counter only after an attempted write."""
        if self.path is not None:
            with _WriteBoundary(self.path, self.health, reason):
                write_state_atomic(self.path, self.snapshot())

    def event(self, kind: str, timestamp: float, fields: JsonObject) -> None:
        """Enqueue before appending, then preserve event caps and immediate persistence."""
        entry: JsonObject = {"ts": float(timestamp), "kind": str(kind)}
        entry.update({str(key): value for key, value in fields.items()})
        if self.outbox is not None:
            self.outbox.enqueue(str(kind), occurred_at=float(timestamp),
                                details={str(key): value for key, value in fields.items()})
        events = self.records.activity.events
        events.append(entry)
        if len(events) > _EVENT_LIMIT:
            del events[:max(0, len(events) - _EVENT_RETAINED)]
        if self.outbox is not None and self.path is not None:
            self.persist("event")

    async def flush(self, client: AsyncClient) -> None:
        """Keep native retry results and pending count without asserting receipt acceptance."""
        if self.outbox is None or self.outbox.pending_count == 0:
            return
        attempts = await self.outbox.flush(client)
        for attempt in attempts:
            log = LOGGER.info if attempt.success else LOGGER.warning
            log("PitchAI Events Bus delivery success=%s delivery_id=%s status=%s "
                "event_id=%s error=%s pending=%s", attempt.success, attempt.delivery_id,
                attempt.status_code, attempt.event_id, attempt.error, self.outbox.pending_count)
