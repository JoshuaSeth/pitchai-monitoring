# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed schema-six state normalization at the monitor's restart boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .cycle_values import bool_field, coerce_float, coerce_int
from .history import coerce_history
from .state_sections import decode_health_sections, default_monitor_state
from .state_storage import read_state_value
from .state_values import coerce_bool_dict, coerce_int_dict, coerce_list_of_dicts, coerce_signal_history

if TYPE_CHECKING:
    from pathlib import Path

    from .event_bus_delivery import JsonObject, JsonValue


def load_monitor_state(path: Path) -> JsonObject:
    """Read and normalize state without changing its persisted version or bytes.

    Returns:
        The legacy-compatible state used to resume independent monitor counters.
    """
    raw = read_state_value(path)
    return decode_monitor_state(raw)


def load_last_ok_state(path: Path) -> dict[str, bool]:
    """Read the original last-ok view for callers using the legacy helper.

    Returns:
        A fresh map of persisted effective domain health.
    """
    state = load_monitor_state(path)
    return coerce_bool_dict(state.get("last_ok"))


def decode_monitor_state(raw: JsonValue) -> JsonObject:
    """Normalize current or legacy state with the unchanged schema-six defaults.

    Returns:
        Fresh defaults plus the previously supported retained values.
    """
    state = default_monitor_state()
    if not isinstance(raw, dict):
        return state
    state["version"] = coerce_int(raw.get("version"), default=coerce_int(state.get("version")))
    history_mode = str(raw.get("history_ok_mode") or "").strip().lower()
    state["history_ok_mode"] = history_mode if history_mode in {"observed", "effective"} else str(
        state.get("history_ok_mode") or "observed",
    )
    # Preserve the early legacy return, including omission of newer fields.
    if isinstance(raw.get("last_ok"), dict) and not any(key in raw for key in ("fail_streak", "success_streak")):
        state["last_ok"] = dict(coerce_bool_dict(raw.get("last_ok")))
        return state
    if all(isinstance(value, bool) for value in raw.values()):
        state["last_ok"] = dict(coerce_bool_dict(raw))
        return state
    state["last_ok"] = dict(coerce_bool_dict(raw.get("last_ok")))
    state["fail_streak"] = dict(coerce_int_dict(raw.get("fail_streak")))
    state["success_streak"] = dict(coerce_int_dict(raw.get("success_streak")))
    history: JsonObject = {}
    for domain, samples in coerce_history(raw.get("history")).items():
        history[domain] = list(samples)
    state["history"] = history
    state["browser_degraded_last_notice_ts"] = coerce_float(raw.get("browser_degraded_last_notice_ts"))
    signals: JsonObject = {}
    for name, samples in coerce_signal_history(raw.get("signal_history")).items():
        signals[name] = list(samples)
    state["signal_history"] = signals
    state["dispatch_history"] = list(coerce_list_of_dicts(raw.get("dispatch_history"), max_items=1000))
    dispatch_last = raw.get("dispatch_last")
    if isinstance(dispatch_last, dict):
        state["dispatch_last"] = dispatch_last
    state["events"] = list(coerce_list_of_dicts(raw.get("events"), max_items=5000))
    state["event_bus_outbox"] = raw.get("event_bus_outbox", [])
    snapshot = raw.get("host_last_snapshot")
    if isinstance(snapshot, dict):
        state["host_last_snapshot"] = snapshot
    state["browser_degraded_active"] = bool_field(raw, "browser_degraded_active", default=False)
    state["browser_degraded_first_seen_ts"] = coerce_float(raw.get("browser_degraded_first_seen_ts"))
    error = raw.get("browser_launch_last_error")
    state["browser_launch_last_error"] = error[:800] if isinstance(error, str) and error.strip() else None
    state.update(decode_health_sections(raw))
    return state
