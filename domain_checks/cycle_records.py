# Copyright (c) 2026 PitchAI. All rights reserved.
"""Retained domain records shared by the native cycle and state writer."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self, cast

from .history_migration import migrate_effective_history
from .monitor_state import load_monitor_state

if TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType

    from .event_bus_delivery import JsonObject, JsonValue
    from .history import Sample

LOGGER = logging.getLogger("service-monitoring")


class _MigrationBoundary:
    """Keep the existing migration failure policy separate from record typing."""

    def __enter__(self) -> Self:
        return self

    def __exit__(self, _kind: type[BaseException] | None, error: BaseException | None,
                 _traceback: TracebackType | None) -> bool:
        if not isinstance(error, Exception):
            return False
        LOGGER.error("Failed to migrate history ok mode to effective", exc_info=error)
        return True


@dataclass
class DomainCounters:
    """Independent effective health and debounce counters for each domain."""

    last_ok: dict[str, bool] = field(default_factory=dict)
    fail_streak: dict[str, int] = field(default_factory=dict)
    success_streak: dict[str, int] = field(default_factory=dict)


@dataclass
class ActivityRecords:
    """The existing event and dispatch collections, with no new journal."""

    dispatch_history: list[JsonObject] = field(default_factory=list)
    dispatch_last: dict[str, JsonObject] = field(default_factory=dict)
    events: list[JsonObject] = field(default_factory=list)


@dataclass
class CycleRecords:
    """Keep the normalized state collections and their live mutable aliases."""

    disk: JsonObject = field(default_factory=dict)
    domains: DomainCounters = field(default_factory=DomainCounters)
    activity: ActivityRecords = field(default_factory=ActivityRecords)
    history: dict[str, list[Sample]] = field(default_factory=dict)
    signals: dict[str, list[list[JsonValue]]] = field(default_factory=dict)
    host_snapshot: JsonObject = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None, *, down_after_failures: int, up_after_successes: int) -> CycleRecords:
        """Resume existing normalized schema-six state without changing its file.

        Returns:
            The same defaults, history migration and independent domain maps.
        """
        state = cls()
        if path is None:
            return state
        disk = load_monitor_state(path)
        state.disk = disk
        # The state loader normalizes these sections. Finite JSON casts express
        # their mutable collection shapes without an additional copy or coercion.
        state.domains.last_ok.update(cast("dict[str, bool]", disk.get("last_ok") or {}))
        state.domains.fail_streak.update(cast("dict[str, int]", disk.get("fail_streak") or {}))
        state.domains.success_streak.update(cast("dict[str, int]", disk.get("success_streak") or {}))
        state.history = cast("dict[str, list[Sample]]", disk.get("history") or {})
        signals = disk.get("signal_history")
        state.signals = cast("dict[str, list[list[JsonValue]]]", signals) if isinstance(signals, dict) else {}
        dispatch = disk.get("dispatch_history")
        state.activity.dispatch_history = cast("list[JsonObject]", dispatch) if isinstance(dispatch, list) else []
        last = disk.get("dispatch_last")
        state.activity.dispatch_last = cast("dict[str, JsonObject]", last) if isinstance(last, dict) else {}
        events = disk.get("events")
        state.activity.events = cast("list[JsonObject]", events) if isinstance(events, list) else []
        host = disk.get("host_last_snapshot")
        state.host_snapshot = host if isinstance(host, dict) else {}
        state.migrate(down_after_failures, up_after_successes)
        return state

    def migrate(self, down_after_failures: int, up_after_successes: int) -> None:
        """Convert only the previous observed-history mode with the same fallback."""
        mode = str(self.disk.get("history_ok_mode") or "").strip().lower()
        if mode == "effective" or not self.history:
            return
        with _MigrationBoundary():
            self.history = migrate_effective_history(
                cast("JsonObject", self.history), down_after_failures=down_after_failures,
                up_after_successes=up_after_successes,
            )
            LOGGER.info("Migrated history ok mode to effective prev_mode=%s domains=%s",
                        mode or "unknown", len(self.history))

    def snapshot(self) -> JsonObject:
        """Capture domain collections with the original history/event caps.

        Returns:
            A new outer object, retaining live inner maps and shallow list slices.
        """
        return {
            "last_ok": cast("JsonObject", self.domains.last_ok),
            "fail_streak": cast("JsonObject", self.domains.fail_streak),
            "success_streak": cast("JsonObject", self.domains.success_streak),
            "history": cast("JsonObject", self.history),
            "signal_history": cast("JsonObject", self.signals),
            "dispatch_history": list(self.activity.dispatch_history[-500:]),
            "dispatch_last": cast("JsonObject", self.activity.dispatch_last),
            "events": list(self.activity.events[-2000:]),
        }
