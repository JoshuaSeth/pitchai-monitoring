# Copyright (c) 2026 PitchAI. All rights reserved.
"""Dispatcher availability state and durable triage records."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from domain_checks.monitor_values import float_value
from domain_checks.telegram import send_telegram_message

if TYPE_CHECKING:
    import httpx

    from domain_checks.dispatch_client import DispatchConfig
    from domain_checks.monitor_runtime_state import RuntimeState
    from domain_checks.telegram import TelegramConfig
    from domain_checks.types import JsonObject

_MAX_DISPATCH_HISTORY = 2_000
_RETAINED_DISPATCH_HISTORY = 1_500
_MAX_EVENTS = 10_000
_RETAINED_EVENTS = 8_000


def dispatch_is_enabled(config: DispatchConfig | None, state: JsonObject) -> bool:
    """Return whether dispatcher escalation is currently available."""
    if config is None:
        return False
    disabled_until = state.get("disabled_until_monotonic")
    if isinstance(disabled_until, bool | int | float | str) and time.monotonic() >= float(disabled_until):
        state["enabled"] = True
        state["disabled_reason"] = None
        state["disabled_until_monotonic"] = None
    return state.get("enabled") is not False


def disable_dispatch(state: JsonObject, *, reason: str, cooldown_seconds: float | None) -> None:
    """Disable dispatch permanently or until a monotonic cooldown expires."""
    state["enabled"] = False
    state["disabled_reason"] = reason
    state["disabled_until_monotonic"] = time.monotonic() + cooldown_seconds if cooldown_seconds is not None else None


def dispatch_should_notify(state: JsonObject, *, min_interval_seconds: float) -> bool:
    """Rate-limit operator notices for dispatcher disablement.

    Returns:
        Whether the caller should send an operator notice now.
    """
    now = time.monotonic()
    last = float_value(state.get("last_notify_monotonic"))
    if last > 0 and now - last < min_interval_seconds:
        return False
    state["last_notify_monotonic"] = now
    return True


def record_dispatch(state: RuntimeState, entry: JsonObject) -> None:
    """Store a bounded triage result and matching dashboard event."""
    entry.setdefault("ts", time.time())
    key = str(entry["state_key"])
    state.collections.dispatch_history.append(entry)
    if len(state.collections.dispatch_history) > _MAX_DISPATCH_HISTORY:
        del state.collections.dispatch_history[:-_RETAINED_DISPATCH_HISTORY]
    state.collections.dispatch_last[key] = entry
    state.collections.events.append({
        "ts": entry["ts"],
        "kind": "dispatch_completed",
        "state_key": key,
        "title": str(entry["title"]),
        "queue_state": str(entry.get("queue_state") or ""),
        "ok": bool(entry.get("ok")),
        "ui_url": str(entry.get("ui_url") or ""),
    })
    if len(state.collections.events) > _MAX_EVENTS:
        del state.collections.events[:-_RETAINED_EVENTS]


async def notify_dispatch_disabled(
    http_client: httpx.AsyncClient,
    telegram: TelegramConfig,
    state: JsonObject,
    details: str,
) -> None:
    """Send one operator-facing dispatcher disablement notice."""
    reason = state.get("disabled_reason") or "unknown"
    status = "until token is fixed/restarted" if state.get("disabled_until_monotonic") is None else "temporarily"
    message = f"Dispatcher escalation is disabled.\nReason: {reason}\nStatus: {status}\nDetails: {details}"
    await send_telegram_message(http_client, telegram, message)
