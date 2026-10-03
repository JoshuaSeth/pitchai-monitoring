# Copyright (c) 2026 PitchAI. All rights reserved.
"""Browser restart state keeps notice age separate from fresh process counters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .cycle_values import coerce_float, coerce_int, required_float

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .browser_admission import BrowserStateValue
    from .config_values import ConfigValue
    from .event_bus_delivery import JsonObject, JsonValue


def restore_browser_state(
    disk: Mapping[str, JsonValue], minimum_memory: ConfigValue | bytes,
) -> dict[str, BrowserStateValue]:
    """Resume notice identity without renewing timestamps or adopting a browser.

    Returns:
        Persisted degradation/notice fields and fresh per-process retry counters.

    A malformed first-seen time keeps the old zero fallback. A malformed last
    notice time still fails startup rather than silently enabling another notice.
    """
    minimum = coerce_int(minimum_memory, default=2048) if isinstance(minimum_memory, (str, bytes, int, float)) else 2048
    error = disk.get("browser_launch_last_error")
    return {
        "browser_degraded_active": bool(disk.get("browser_degraded_active", False)),
        "browser_degraded_first_seen_ts": coerce_float(disk.get("browser_degraded_first_seen_ts") or 0.0),
        "browser_degraded_last_notice_ts": required_float(disk.get("browser_degraded_last_notice_ts") or 0.0),
        "browser_degraded_recover_streak": 0,
        "browser_degraded_notice_min_interval_seconds": 6 * 3600,
        "browser_launch_fail_count": 0,
        "browser_launch_next_try_ts": 0.0,
        "browser_launch_last_error": str(error)[:800] if isinstance(error, str) and error.strip() else None,
        "browser_min_mem_available_mb": max(0, minimum),
    }


def browser_state_snapshot(state: Mapping[str, BrowserStateValue]) -> JsonObject:
    """Persist only the original browser fields, without renewing their clocks.

    Returns:
        Current degradation, bounded launch error and original notice timestamps.
    """
    error = state.get("browser_launch_last_error")
    return {
        "browser_degraded_active": bool(state.get("browser_degraded_active", False)),
        "browser_degraded_first_seen_ts": required_float(state.get("browser_degraded_first_seen_ts") or 0.0),
        "browser_launch_last_error": str(error)[:800] if isinstance(error, str) else None,
        "browser_degraded_last_notice_ts": required_float(state.get("browser_degraded_last_notice_ts") or 0.0),
    }
