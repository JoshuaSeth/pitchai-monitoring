# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict JSON shape readers for quality snapshot and checker payloads."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pitchai_quality.ratchet_model import JsonValue


def decode_json(output: bytes) -> JsonValue:
    """Decode one checker's machine-readable output.

    Returns:
        The decoded JSON value.
    """
    return cast("JsonValue", json.loads(output))


def expect_object(value: JsonValue, description: str) -> dict[str, JsonValue]:
    """Require a JSON object.

    Returns:
        The validated object.

    Raises:
        TypeError: If the value is not an object.
    """
    if not isinstance(value, dict):
        message = f"{description} must be a JSON object"
        raise TypeError(message)
    return value


def expect_array(value: JsonValue, description: str) -> list[JsonValue]:
    """Require a JSON array.

    Returns:
        The validated array.

    Raises:
        TypeError: If the value is not an array.
    """
    if not isinstance(value, list):
        message = f"{description} must be a JSON array"
        raise TypeError(message)
    return value


def expect_integer(value: JsonValue, description: str, *, offset: int = 0) -> int:
    """Require a non-boolean JSON integer and apply an offset.

    Returns:
        The validated integer plus the requested offset.

    Raises:
        TypeError: If the value is not an integer.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        message = f"{description} must be an integer"
        raise TypeError(message)
    return value + offset


def expect_text(value: JsonValue, description: str) -> str:
    """Require JSON text.

    Returns:
        The validated text.

    Raises:
        TypeError: If the value is not text.
    """
    if not isinstance(value, str):
        message = f"{description} must be text"
        raise TypeError(message)
    return value
