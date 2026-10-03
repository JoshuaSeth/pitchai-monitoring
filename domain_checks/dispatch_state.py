# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing dispatcher enablement, cooldown and notice cadence."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .cycle_values import required_float

if TYPE_CHECKING:
    from .dispatch_client import DispatchConfig
    from .event_bus_delivery import JsonObject


def dispatch_state_reenable_if_due(dispatch_state: JsonObject) -> None:
    """Re-enable only an elapsed finite cooldown, preserving permanent stops."""
    if dispatch_state.get("enabled") is True:
        return
    disabled_until = dispatch_state.get("disabled_until_monotonic")
    if disabled_until is None:
        return
    if time.monotonic() >= required_float(disabled_until):
        dispatch_state["enabled"] = True
        dispatch_state["disabled_until_monotonic"] = None
        dispatch_state["disabled_reason"] = None


def dispatch_is_enabled(dispatch_cfg: DispatchConfig | None, dispatch_state: JsonObject) -> bool:
    """Return existing enablement after evaluating an elapsed cooldown."""
    if not dispatch_cfg:
        return False
    dispatch_state_reenable_if_due(dispatch_state)
    return bool(dispatch_state.get("enabled", True))


def dispatch_disable(dispatch_state: JsonObject, *, reason: str, cooldown_seconds: float | None = None) -> None:
    """Record permanent disablement or the existing minimum one-second cooldown."""
    dispatch_state["enabled"] = False
    dispatch_state["disabled_reason"] = reason
    if cooldown_seconds is None:
        dispatch_state["disabled_until_monotonic"] = None
    else:
        dispatch_state["disabled_until_monotonic"] = time.monotonic() + max(1.0, float(cooldown_seconds))


def dispatch_should_notify(dispatch_state: JsonObject, *, min_interval_seconds: float = 3600.0) -> bool:
    """Return whether the existing monotonic notice interval has elapsed."""
    last = required_float(dispatch_state.get("last_notify_monotonic") or 0.0)
    now = time.monotonic()
    if (now - last) >= float(min_interval_seconds):
        dispatch_state["last_notify_monotonic"] = now
        return True
    return False
