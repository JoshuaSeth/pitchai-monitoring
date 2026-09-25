# Copyright (c) 2026 PitchAI. All rights reserved.
"""Provide a closed recursive type for guardian JSON boundaries."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Final

type JsonScalar = bool | int | float | str | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


type JsonDecoder = Callable[[str | bytes | bytearray], JsonValue]


def _decoder() -> JsonDecoder:
    """Constrain the standard decoder to the recursive JSON contract.

    Returns:
        The resulting value.

    """
    decoder: JsonDecoder = json.loads
    return decoder


decode_json: Final[JsonDecoder] = _decoder()
