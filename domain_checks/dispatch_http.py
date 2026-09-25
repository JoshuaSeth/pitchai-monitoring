# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared response decoding for Dispatcher HTTP boundaries."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import httpx

    from domain_checks.types import JsonObject, JsonValue

DISPATCH_TIMEOUT_SECONDS = 30.0
READ_TIMEOUT_SECONDS = 20.0


def decode_json_object(response: httpx.Response, *, response_name: str) -> JsonObject:
    """Decode one strict Dispatcher response object.

    Returns:
        The decoded JSON object.

    Raises:
        TypeError: The response contains JSON with a non-object root.
        ValueError: The response is not valid JSON.
    """
    try:
        data = cast("JsonValue", response.json())
    except json.JSONDecodeError as exc:
        message = f"Unexpected dispatcher {response_name} response (invalid JSON)"
        raise ValueError(message) from exc
    if not isinstance(data, dict):
        message = f"Unexpected dispatcher {response_name} response (not a JSON object)"
        raise TypeError(message)
    return data
