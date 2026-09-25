# Copyright (c) 2026 PitchAI. All rights reserved.
"""Define the dashboard's recursively typed JSON transport contract."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Final

type JsonPrimitive = bool | int | float | str | None
type JsonValue = JsonPrimitive | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


type DocumentDecoder = Callable[[str | bytes | bytearray], JsonValue]


def _document_decoder() -> DocumentDecoder:
    """Constrain the standard decoder to dashboard JSON values.

    Returns:
        The resulting value.

    """
    decoder: DocumentDecoder = json.loads
    return decoder


_decode_document: Final[DocumentDecoder] = _document_decoder()


def decode_document(source: str | bytes | bytearray) -> JsonValue:
    """Decode an untrusted dashboard document into its recursive value type.

    Returns:
        The resulting value.

    """
    return _decode_document(source)
