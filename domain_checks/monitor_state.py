# Copyright (c) 2026 PitchAI. All rights reserved.
"""Durable monitor-state codec and debounced status transitions."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, TypedDict, Unpack, cast

from domain_checks.history import coerce_history
from domain_checks.monitor_state_schema import default_monitor_state
from domain_checks.monitor_state_sections import normalize_sections
from domain_checks.monitor_value_collections import (
    bool_dict,
    bounded_objects,
    int_dict,
    object_dict,
    signal_history,
)
from domain_checks.monitor_values import bool_value, float_value, int_value, json_object

if TYPE_CHECKING:
    from pathlib import Path

    from domain_checks.types import JsonObject, JsonValue

LOGGER = logging.getLogger("service-monitoring")


def _read_state(path: Path) -> JsonValue | None:
    try:
        return cast("JsonValue", json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        LOGGER.warning("Failed to read state file path=%s error=%s", path, exc)
        return None


def _history_mode(raw: JsonObject, state: JsonObject) -> str:
    value = str(raw.get("history_ok_mode") or "").strip().lower()
    if value in {"observed", "effective"}:
        return value
    return str(state["history_ok_mode"])


def _legacy_state(raw: JsonObject, state: JsonObject) -> JsonObject | None:
    has_only_last_ok = isinstance(raw.get("last_ok"), dict) and not any(
        key in raw for key in ("fail_streak", "success_streak")
    )
    if has_only_last_ok:
        state["last_ok"] = bool_dict(raw.get("last_ok"))
        return state
    if raw and all(isinstance(value, bool) for value in raw.values()):
        state["last_ok"] = bool_dict(raw)
        return state
    return None


def _normalize_common(raw: JsonObject, state: JsonObject) -> None:
    state["last_ok"] = bool_dict(raw.get("last_ok"))
    state["fail_streak"] = int_dict(raw.get("fail_streak"))
    state["success_streak"] = int_dict(raw.get("success_streak"))
    state["history"] = coerce_history(raw.get("history"))
    state["signal_history"] = signal_history(raw.get("signal_history"))
    state["dispatch_history"] = bounded_objects(raw.get("dispatch_history"), max_items=1000)
    state["dispatch_last"] = object_dict(raw.get("dispatch_last"))
    state["events"] = bounded_objects(raw.get("events"), max_items=5000)
    state["event_bus_outbox"] = raw.get("event_bus_outbox", [])
    state["host_last_snapshot"] = json_object(raw.get("host_last_snapshot"))


def _normalize_browser(raw: JsonObject, state: JsonObject) -> None:
    state["browser_degraded_active"] = bool_value(raw.get("browser_degraded_active"), default=False)
    state["browser_degraded_first_seen_ts"] = float_value(raw.get("browser_degraded_first_seen_ts"))
    state["browser_degraded_last_notice_ts"] = float_value(raw.get("browser_degraded_last_notice_ts"))
    launch_error = raw.get("browser_launch_last_error")
    state["browser_launch_last_error"] = (
        launch_error[:800] if isinstance(launch_error, str) and launch_error.strip() else None
    )


def load_monitor_state(path: Path) -> JsonObject:
    """Load persisted monitor state while preserving supported legacy shapes.

    Returns:
        The normalized canonical monitor state.
    """
    state = default_monitor_state()
    raw_value = _read_state(path)
    if not isinstance(raw_value, dict):
        return state
    raw = raw_value
    state["version"] = int_value(raw.get("version"), default=int_value(state.get("version")))
    state["history_ok_mode"] = _history_mode(raw, state)
    legacy = _legacy_state(raw, state)
    if legacy is not None:
        return legacy
    _normalize_common(raw, state)
    _normalize_browser(raw, state)
    normalize_sections(raw, state)
    return state


class DebounceOptions(TypedDict):
    """Required keyword contract for a debounced status update."""

    prev_effective_ok: bool
    observed_ok: bool
    fail_streak: int
    success_streak: int
    down_after_failures: int
    up_after_successes: int


def update_effective_ok(**options: Unpack[DebounceOptions]) -> tuple[bool, int, int, bool]:
    """Apply consecutive-failure and consecutive-success transition thresholds.

    Returns:
        Effective status, failure streak, success streak, and down transition.
    """
    fail_streak = options["fail_streak"]
    success_streak = options["success_streak"]
    if options["observed_ok"]:
        success_streak += 1
        fail_streak = 0
    else:
        fail_streak += 1
        success_streak = 0
    down_threshold = max(1, options["down_after_failures"])
    up_threshold = max(1, options["up_after_successes"])
    previous = options["prev_effective_ok"]
    effective = fail_streak < down_threshold if previous else success_streak >= up_threshold
    return effective, fail_streak, success_streak, previous and not effective


def write_state_atomic(path: Path, payload: JsonObject) -> None:
    """Atomically replace a persisted monitor-state file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    _ = temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    _ = temporary.replace(path)
