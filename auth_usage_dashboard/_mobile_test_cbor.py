# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed runtime CBOR encoder boundary for cryptographic test fixtures."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from .mobile_auth_codec import CborValue


class _Encoder(Protocol):
    """Encode one validated recursive CBOR test value."""

    def __call__(self, value: CborValue) -> bytes:
        """Return the runtime encoding."""
        raise NotImplementedError

    def encoder_protocol_marker(self) -> None:
        """Identify the dynamic encoder contract to static tooling."""
        raise NotImplementedError


_CBOR_MODULE = cast("dict[str, object]", vars(import_module("cbor2")))
CBOR_ENCODER = cast("_Encoder", _CBOR_MODULE["dumps"])
