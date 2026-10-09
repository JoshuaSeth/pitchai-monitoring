# Copyright (c) 2026 PitchAI. All rights reserved.
"""Read the existing dashboard snapshot and YAML configuration without mutation."""

from __future__ import annotations

import json
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import yaml

from domain_checks.history import coerce_history

if TYPE_CHECKING:
    from domain_checks.config_values import ConfigValue
    from domain_checks.event_bus_delivery import JsonObject, JsonValue


def load_yaml(path: Path) -> dict[str, ConfigValue]:
    """Retain the display-only empty fallback for unreadable or invalid YAML.

    Returns:
        The parsed mapping, including YAML date scalars, or an empty mapping.
    """
    # This boundary intentionally keeps the existing dashboard fallback; it is
    # not the monitor's stricter startup configuration loader.
    with suppress(Exception):
        decoded = cast("ConfigValue", yaml.safe_load(path.read_text(encoding="utf-8"))) or {}
        if isinstance(decoded, dict):
            return decoded
    return {}


def load_json(path: Path) -> JsonObject:
    """Read retained JSON with the existing display-only unavailable fallback.

    Returns:
        The parsed object, or an empty object on read/decoding failure.
    """
    # All ordinary IO/decoder errors retain the established display fallback.
    with suppress(Exception):
        decoded = cast("JsonValue", json.loads(path.read_text(encoding="utf-8")))
        if isinstance(decoded, dict):
            return decoded
    return {}


@dataclass(frozen=True)
class MonitorData:
    """The original six-field immutable snapshot container."""

    state: JsonObject
    config: dict[str, ConfigValue]
    state_path: str
    config_path: str
    loaded_at_ts: float
    state_error: str | None


def load_monitor_data(*, state_path: str, config_path: str) -> MonitorData:
    """Load state then config and normalize history before determining the error.

    Returns:
        The same snapshot/error precedence, without writing either input.
    """
    state_file = Path(str(state_path or "").strip())
    config_file = Path(str(config_path or "").strip())
    state_raw = load_json(state_file) if str(state_file) else {}
    config_raw = load_yaml(config_file) if str(config_file) else {}
    history = coerce_history(state_raw.get("history"))
    state_raw["history"] = cast("JsonValue", history)
    state_error = None
    if not state_raw:
        state_error = f"missing_or_invalid_state: {state_file}"
    if not config_raw:
        state_error = (state_error + "; " if state_error else "") + f"missing_or_invalid_config: {config_file}"
    return MonitorData(state_raw, config_raw, str(state_file), str(config_file), time.time(), state_error)
