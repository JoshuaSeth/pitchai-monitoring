# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict JSON helpers for hotpath persistence."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable

    from .hotpath_types import JsonValue

_decode_json = cast("Callable[[str], JsonValue]", json.loads)


class StoredJsonError(TypeError):
    """Persisted JSON does not match the strict object contract."""


def canonical_json(value: dict[str, JsonValue]) -> str:
    """Encode strict JSON for hashing, storage, and delivery identities.

    Returns:
        Stable ASCII JSON without insignificant whitespace.
    """
    if not value:
        return "{}"
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True)


def decode_object(document: str) -> dict[str, JsonValue]:
    """Decode and validate one stored JSON object.

    Returns:
        The strict recursive JSON object.

    Raises:
        StoredJsonError: If the stored value is not an object.
    """
    value = _decode_json(document)
    if not isinstance(value, dict):
        error = "stored JSON value must be an object"
        raise StoredJsonError(error)
    _ = canonical_json(value)
    return value
