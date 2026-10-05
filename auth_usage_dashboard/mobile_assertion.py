# Copyright (c) 2026 PitchAI. All rights reserved.
"""Apple App Attest assertion verification."""

from __future__ import annotations

import hashlib
import logging
import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from .mobile_auth_codec import decode_base64, decode_cbor
from .mobile_auth_errors import MobileAuthError, MobileAuthFailure

MAX_ASSERTION_BYTES = 16 * 1_024
ASSERTION_SUPPORTED_FLAGS = frozenset({0x00, 0x40})
_AUTHENTICATOR_DATA_BYTES = 37
_LOGGER = logging.getLogger(__name__)


def verify_assertion(
    *,
    assertion_object: str,
    client_data: bytes,
    app_id: str,
    public_key: ec.EllipticCurvePublicKey,
    previous_counter: int,
) -> int:
    """Verify one monotonic App Attest assertion.

    Returns:
        The authenticated assertion counter.

    Raises:
        MobileAuthError: If the assertion is malformed, replayed, or invalid.
    """
    raw = decode_base64(assertion_object, maximum=MAX_ASSERTION_BYTES)
    payload = decode_cbor(raw)
    if not isinstance(payload, dict) or set(payload) != {"signature", "authenticatorData"}:
        raise MobileAuthError(MobileAuthFailure.ASSERTION_INVALID)
    signature = payload.get("signature")
    auth_data = payload.get("authenticatorData")
    if not isinstance(signature, bytes) or not isinstance(auth_data, bytes):
        raise MobileAuthError(MobileAuthFailure.ASSERTION_INVALID)
    if len(auth_data) != _AUTHENTICATOR_DATA_BYTES:
        raise MobileAuthError(MobileAuthFailure.ASSERTION_AUTH_DATA_INVALID)
    _verify_authenticator_data(auth_data, app_id=app_id, previous_counter=previous_counter)
    nonce = hashlib.sha256(auth_data + hashlib.sha256(client_data).digest()).digest()
    public_key.verify(signature, nonce, ec.ECDSA(hashes.SHA256()))
    return int.from_bytes(auth_data[33:37], "big")


def _verify_authenticator_data(
    auth_data: bytes,
    *,
    app_id: str,
    previous_counter: int,
) -> None:
    flags = auth_data[32]
    if flags not in ASSERTION_SUPPORTED_FLAGS:
        _LOGGER.warning(
            "App Attest assertion rejected unsupported authenticator flags=0x%02x",
            flags,
        )
        raise MobileAuthError(MobileAuthFailure.ASSERTION_FLAGS_INVALID)
    expected_rp_id = hashlib.sha256(app_id.encode()).digest()
    if not secrets.compare_digest(auth_data[:32], expected_rp_id):
        raise MobileAuthError(MobileAuthFailure.ASSERTION_APPLICATION_MISMATCH)
    counter = int.from_bytes(auth_data[33:37], "big")
    if counter <= previous_counter:
        raise MobileAuthError(MobileAuthFailure.ASSERTION_REPLAYED)
