# Copyright (c) 2026 PitchAI. All rights reserved.
"""API configuration values and JSON traversal without changing coercion policy."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from .synthetic_values import substitute_env_refs

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject, JsonValue


def get_path(value: JsonValue, path: str) -> tuple[bool, JsonValue]:
    """Return the original dotted mapping/list lookup, including rejected empty segments."""
    current = value
    for segment in (path or "").split("."):
        key = segment.strip()
        if not key:
            return False, None
        if isinstance(current, list):
            # The prior index conversion refused every ordinary conversion failure.
            index = None
            with suppress(Exception):
                index = int(key)
            if index is None or not 0 <= index < len(current):
                return False, None
            current = current[index]
            continue
        if isinstance(current, dict) and key in current:
            current = current[key]
            continue
        return False, None
    return True, current


def as_list(value: JsonValue) -> list[JsonValue]:
    """Return a present list unchanged, an empty list for None or a wrapped scalar."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def headers_with_env(headers: JsonObject) -> dict[str, str]:
    """Return original stringified keys and shared fail-loud placeholder values."""
    converted: dict[str, str] = {}
    for key, value in headers.items():
        converted[str(key)] = substitute_env_refs(str(value))
    return converted


def missing_paths(data: JsonValue, required: list[str]) -> list[str]:
    """Return at most fifty missing path names in configured order."""
    missing: list[str] = []
    for path in required[:50]:
        exists, _value = get_path(data, path)
        if not exists:
            missing.append(path)
    return missing


def unequal_paths(data: JsonValue, equal: JsonObject) -> list[str]:
    """Return the original fifty-entry missing/value diagnostics without normalization."""
    mismatches: list[str] = []
    for path, expected in list(equal.items())[:50]:
        exists, observed = get_path(data, str(path))
        if not exists:
            mismatches.append(f"{path}: missing")
        elif observed != expected:
            mismatches.append(f"{path}: got={observed!r} expected={expected!r}")
    return mismatches
