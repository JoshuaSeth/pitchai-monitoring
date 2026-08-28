# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict CBOR and Base64 boundaries for App Attest payloads."""

from __future__ import annotations

import base64
import io
import re
import secrets
from importlib import import_module
from typing import NamedTuple, Protocol, cast

from .mobile_auth_errors import MobileAuthError, MobileAuthFailure

type CborKey = str | int | bytes
type CborScalar = str | int | float | bool | bytes | None
type CborValue = CborScalar | list[CborValue] | dict[CborKey, CborValue]


class _UnsupportedCborValue(Protocol):
    """Static placeholder for runtime CBOR extension values we reject."""

    def unsupported_cbor_marker(self) -> None:
        """Distinguish unsupported values from the accepted recursive union."""
        raise NotImplementedError

    def unsupported_cbor_type_marker(self) -> None:
        """Provide a second static marker for Pylint protocol shape."""
        raise NotImplementedError


type _RuntimeCborKey = CborKey | _UnsupportedCborValue
type _RuntimeCborValue = (
    CborScalar | list[_RuntimeCborValue] | dict[_RuntimeCborKey, _RuntimeCborValue] | _UnsupportedCborValue
)

MAX_KEY_ID_BYTES = 128
_DECODED_KEY_ID_BYTES = 32
_MAX_RAW_KEY_ID_BYTES = 64
_BASE64_PATTERN = re.compile(
    r"(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?",
)


class _Decoder(Protocol):
    """Typed surface of one dynamically loaded CBOR decoder."""

    def decode(self) -> _RuntimeCborValue:
        """Decode one CBOR value."""
        raise NotImplementedError

    def decoder_protocol_marker(self) -> None:
        """Identify the dynamic decoder contract to static tooling."""
        raise NotImplementedError


class _DecoderFactory(Protocol):
    """Construct a CBOR decoder over one binary stream."""

    def __call__(self, stream: io.BytesIO) -> _Decoder:
        """Create the decoder."""
        raise NotImplementedError

    def factory_protocol_marker(self) -> None:
        """Identify the dynamic factory contract to static tooling."""
        raise NotImplementedError


class _CborRuntime(NamedTuple):
    """Typed handles from the runtime-only CBOR dependency."""

    decoder_factory: _DecoderFactory
    decode_error: type[Exception]


_CBOR_MODULE = cast("dict[str, object]", vars(import_module("cbor2")))
_CBOR = _CborRuntime(
    decoder_factory=cast("_DecoderFactory", _CBOR_MODULE["CBORDecoder"]),
    decode_error=cast("type[Exception]", _CBOR_MODULE["CBORDecodeError"]),
)
CBOR_DECODE_ERROR = _CBOR.decode_error


def decode_cbor(raw: bytes) -> CborValue:
    """Decode exactly one strict recursive CBOR value.

    Returns:
        A value composed only of the App Attest CBOR contract types.

    Raises:
        MobileAuthError: If trailing data or an unsupported value is present.

    """
    stream = io.BytesIO(raw)
    payload = _CBOR.decoder_factory(stream).decode()
    if stream.read(1):
        raise MobileAuthError(MobileAuthFailure.CBOR_TRAILING_DATA)
    return _validated_cbor_value(payload)


def decode_base64(value: str, *, maximum: int) -> bytes:
    """Decode one size-bounded canonical Base64 value.

    Returns:
        Validated decoded bytes.

    Raises:
        MobileAuthError: If the value is malformed or outside the size bound.
    """
    if not value or len(value) > maximum * 2:
        raise MobileAuthError(MobileAuthFailure.BASE64_INVALID)
    if len(value) % 4 != 0 or _BASE64_PATTERN.fullmatch(value) is None:
        raise MobileAuthError(MobileAuthFailure.BASE64_MALFORMED)
    decoded = base64.b64decode(value, validate=True)
    canonical = base64.b64encode(decoded).decode("ascii")
    if not secrets.compare_digest(canonical, value):
        raise MobileAuthError(MobileAuthFailure.BASE64_MALFORMED)
    if not decoded or len(decoded) > maximum:
        raise MobileAuthError(MobileAuthFailure.BASE64_SIZE_INVALID)
    return decoded


def validate_key_id(key_id: str) -> None:
    """Require the Base64 SHA-256 public-key identifier used by App Attest.

    Raises:
        MobileAuthError: If the identifier is not one encoded SHA-256 digest.
    """
    if not 1 <= len(key_id) <= MAX_KEY_ID_BYTES:
        raise MobileAuthError(MobileAuthFailure.KEY_ID_INVALID)
    decoded = decode_base64(key_id, maximum=_MAX_RAW_KEY_ID_BYTES)
    if len(decoded) != _DECODED_KEY_ID_BYTES:
        raise MobileAuthError(MobileAuthFailure.KEY_ID_INVALID)


def _validated_cbor_value(value: _RuntimeCborValue) -> CborValue:
    if value is None or isinstance(value, (str, int, float, bool, bytes)):
        return value
    if isinstance(value, list):
        validated_items = (_validated_cbor_value(item) for item in value)
        return list(validated_items)
    if isinstance(value, dict):
        validated: dict[CborKey, CborValue] = {}
        for raw_key, raw_value in value.items():
            key = _validated_cbor_key(raw_key)
            validated[key] = _validated_cbor_value(raw_value)
        return validated
    raise MobileAuthError(MobileAuthFailure.CBOR_INVALID)


def _validated_cbor_key(value: _RuntimeCborKey) -> CborKey:
    if isinstance(value, (str, int, bytes)):
        return value
    raise MobileAuthError(MobileAuthFailure.CBOR_INVALID)
