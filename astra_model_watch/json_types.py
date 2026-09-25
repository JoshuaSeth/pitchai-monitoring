# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strictly typed validation helpers for untrusted JSON values."""

from __future__ import annotations

from typing import TypeAlias, cast


JsonPrimitive: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
JsonArray: TypeAlias = list[JsonValue]
UntrustedValue: TypeAlias = object


def string_object_dict(value: UntrustedValue) -> JsonObject | None:
    """Return a typed copy when value is a dictionary with only string keys."""
    if not isinstance(value, dict):
        return None
    raw = cast("dict[UntrustedValue, UntrustedValue]", value)
    result: JsonObject = {}
    for key, nested in raw.items():
        if not isinstance(key, str):
            return None
        result[key] = cast("JsonValue", nested)
    return result


def object_list(value: UntrustedValue) -> JsonArray | None:
    """Return a typed copy when value is a JSON-style list."""
    if not isinstance(value, list):
        return None
    raw = cast("list[UntrustedValue]", value)
    return [cast("JsonValue", item) for item in raw]
