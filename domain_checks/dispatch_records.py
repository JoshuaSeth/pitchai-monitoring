# Copyright (c) 2026 PitchAI. All rights reserved.
"""Bounded existing in-memory dispatcher history and completion events."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .cycle_values import coerce_optional_float

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject

HISTORY_LIMIT = 2000
EVENT_LIMIT = 10_000


@dataclass(frozen=True)
class DispatchRecords:
    """References to the cycle's existing collections; no new persistence."""

    history: list[JsonObject] | None = None
    last: dict[str, JsonObject] | None = None
    events: list[JsonObject] | None = None

    def record(self, entry: JsonObject, state_key: str, title: str) -> None:
        """Retain the same entry object, defaults, collection limits and event."""
        entry.setdefault("ts", time.time())
        entry.setdefault("state_key", state_key)
        entry.setdefault("title", title)
        if self.history is not None:
            self.history.append(entry)
            if len(self.history) > HISTORY_LIMIT:
                del self.history[:max(0, len(self.history) - 1500)]
        if self.last is not None:
            key = str(entry.get("state_key") or state_key).strip() or state_key
            self.last[key] = entry
        if self.events is not None:
            timestamp = coerce_optional_float(entry.get("ts") or time.time())
            if timestamp is None:
                return
            self.events.append({
                "ts": timestamp,
                "kind": "dispatch_completed",
                "state_key": str(entry.get("state_key") or state_key),
                "title": str(entry.get("title") or title),
                "queue_state": str(entry.get("queue_state") or ""),
                "ok": bool(entry.get("ok", False)),
                "ui_url": str(entry.get("ui_url") or ""),
            })
            if len(self.events) > EVENT_LIMIT:
                del self.events[:max(0, len(self.events) - 8000)]
