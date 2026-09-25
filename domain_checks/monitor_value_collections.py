# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict persisted-state collection coercion for the service monitor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain_checks.monitor_values import json_array, json_float, json_int, json_object

if TYPE_CHECKING:
    from collections.abc import Iterator

    from domain_checks.types import JsonObject, JsonValue


def bool_dict(value: JsonValue) -> dict[str, bool]:
    """Coerce a persisted mapping to boolean entries.

    Returns:
        A mapping containing only boolean entries.
    """
    return {key: item for key, item in json_object(value).items() if isinstance(item, bool)}


def int_dict(value: JsonValue) -> dict[str, int]:
    """Coerce valid integer entries from a persisted mapping.

    Returns:
        A mapping containing every valid integer entry.
    """
    result: dict[str, int] = {}
    for key, item in json_object(value).items():
        try:
            result[key] = json_int(item)
        except (TypeError, ValueError):
            continue
    return result


def float_dict(value: JsonValue) -> dict[str, float]:
    """Coerce valid float entries from a persisted mapping.

    Returns:
        A mapping containing every valid floating-point entry.
    """
    result: dict[str, float] = {}
    for key, item in json_object(value).items():
        try:
            result[key] = json_float(item)
        except (TypeError, ValueError):
            continue
    return result


def string_list_dict(value: JsonValue) -> dict[str, list[str]]:
    """Coerce string-list entries from a persisted mapping.

    Returns:
        A mapping of keys to non-empty string values.
    """
    result: dict[str, list[str]] = {}
    for key, item in json_object(value).items():
        strings: list[str] = []
        for candidate in json_array(item):
            cleaned = str(candidate or "").strip()
            if cleaned:
                strings.append(cleaned)
        result[key] = strings
    return result


def object_dict(value: JsonValue) -> dict[str, JsonObject]:
    """Retain mapping-valued entries from a persisted mapping.

    Returns:
        A mapping containing only object-valued entries.
    """
    return {key: item for key, item in json_object(value).items() if isinstance(item, dict)}


def bounded_objects(value: JsonValue, *, max_items: int) -> list[JsonObject]:
    """Read a bounded list of persisted JSON objects.

    Returns:
        At most ``max_items`` valid object entries.
    """
    array_items = json_array(value)
    mapping_items = (item for item in array_items if isinstance(item, dict))
    objects = list(mapping_items)
    return objects[: max(1, max_items)]


def signal_history(value: JsonValue, *, max_samples: int = 50_000) -> dict[str, list[list[JsonValue]]]:
    """Read bounded, non-empty monitor signal samples.

    Returns:
        Valid samples grouped by non-empty signal name.
    """
    result: dict[str, list[list[JsonValue]]] = {}
    for key, item in json_object(value).items():
        samples = list(_nonempty_array_entries(json_array(item)))
        if key and samples:
            result[key] = samples[: max(1, max_samples)]
    return result


def _nonempty_array_entries(values: list[JsonValue]) -> Iterator[list[JsonValue]]:
    for value in values:
        if isinstance(value, list) and value:
            yield value
