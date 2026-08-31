# Copyright (c) 2026 PitchAI. All rights reserved.
"""Apple App Attest attestation-object verification."""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ObjectIdentifier

from .mobile_attestation_certificate import decode_nonce_extension, verify_certificate_chain
from .mobile_auth_codec import decode_base64, decode_cbor
from .mobile_auth_errors import MobileAuthError, MobileAuthFailure

if TYPE_CHECKING:
    from .mobile_auth_codec import CborValue

NONCE_EXTENSION_OID = ObjectIdentifier("1.2.840.113635.100.8.2")
DEVELOPMENT_AAGUID = b"appattestdevelop"
PRODUCTION_AAGUID = b"appattest" + (b"\x00" * 7)
MAX_ATTESTATION_BYTES = 64 * 1_024
_CERTIFICATE_CHAIN_LENGTH = 2
_RP_ID_HASH_LENGTH = 32
_ATTESTED_CREDENTIAL_FLAG = 0x40
_AUTH_DATA_HEADER_LENGTH = 55
_CREDENTIAL_IDENTIFIER_LENGTH = 32


@dataclass(frozen=True)
class _AttestationAuthData:
    rp_id_hash: bytes
    counter: int
    aaguid: bytes
    credential_id: bytes
    cose_key: bytes


@dataclass(frozen=True)
class AttestationRequest:
    """Bindings required to verify one App Attest enrollment object."""

    attestation_object: str
    key_id: str
    challenge: bytes
    app_id: str
    environment: str
    root_certificate: x509.Certificate


@dataclass(frozen=True)
class _DecodedAttestation:
    leaf: x509.Certificate
    intermediate: x509.Certificate
    auth_data: bytes
    receipt: bytes


def verify_attestation(request: AttestationRequest) -> tuple[ec.EllipticCurvePublicKey, bytes]:
    """Verify one Apple App Attest enrollment object.

    Returns:
        The attested P-256 public key and opaque Apple receipt.

    """
    decoded = _decode_attestation_object(request.attestation_object)
    verify_certificate_chain(decoded.leaf, decoded.intermediate, request.root_certificate)
    _verify_nonce(decoded.leaf, auth_data=decoded.auth_data, challenge=request.challenge)
    public_key = _attested_public_key(decoded.leaf)
    _verify_key_identifier(public_key, request.key_id)
    parsed = _parse_auth_data(decoded.auth_data)
    _verify_auth_data(
        parsed,
        app_id=request.app_id,
        environment=request.environment,
        key_id=request.key_id,
    )
    _verify_cose_key(parsed.cose_key, public_key)
    return public_key, decoded.receipt


def _decode_attestation_object(encoded: str) -> _DecodedAttestation:
    raw = decode_base64(encoded, maximum=MAX_ATTESTATION_BYTES)
    payload = decode_cbor(raw)
    if not isinstance(payload, dict) or set(payload) != {"fmt", "attStmt", "authData"}:
        raise MobileAuthError(MobileAuthFailure.ATTESTATION_OBJECT_INVALID)
    if payload.get("fmt") != "apple-appattest":
        raise MobileAuthError(MobileAuthFailure.ATTESTATION_FORMAT_INVALID)
    statement = payload.get("attStmt")
    auth_data = payload.get("authData")
    if not isinstance(statement, dict) or not isinstance(auth_data, bytes):
        raise MobileAuthError(MobileAuthFailure.ATTESTATION_OBJECT_INVALID)
    if set(statement) != {"x5c", "receipt"}:
        raise MobileAuthError(MobileAuthFailure.ATTESTATION_STATEMENT_INVALID)
    leaf_bytes, intermediate_bytes = _certificate_bytes(statement.get("x5c"))
    receipt = statement.get("receipt")
    if not isinstance(receipt, bytes) or not receipt:
        raise MobileAuthError(MobileAuthFailure.ATTESTATION_STATEMENT_INVALID)
    return _DecodedAttestation(
        leaf=_load_certificate(leaf_bytes),
        intermediate=_load_certificate(intermediate_bytes),
        auth_data=auth_data,
        receipt=receipt,
    )


def _load_certificate(encoded: bytes) -> x509.Certificate:
    return x509.load_der_x509_certificate(encoded)


def _certificate_bytes(value: CborValue | None) -> tuple[bytes, bytes]:
    if not isinstance(value, list) or len(value) != _CERTIFICATE_CHAIN_LENGTH:
        raise MobileAuthError(MobileAuthFailure.ATTESTATION_STATEMENT_INVALID)
    leaf = value[0]
    intermediate = value[1]
    if not isinstance(leaf, bytes) or not isinstance(intermediate, bytes):
        raise MobileAuthError(MobileAuthFailure.ATTESTATION_STATEMENT_INVALID)
    return leaf, intermediate


def _verify_nonce(
    leaf: x509.Certificate,
    *,
    auth_data: bytes,
    challenge: bytes,
) -> None:
    expected = hashlib.sha256(auth_data + hashlib.sha256(challenge).digest()).digest()
    extension = leaf.extensions.get_extension_for_oid(NONCE_EXTENSION_OID)
    if not isinstance(extension.value, x509.UnrecognizedExtension):
        raise MobileAuthError(MobileAuthFailure.ATTESTATION_NONCE_INVALID)
    actual = decode_nonce_extension(extension.value.value)
    if not secrets.compare_digest(actual, expected):
        raise MobileAuthError(MobileAuthFailure.ATTESTATION_NONCE_MISMATCH)


def _attested_public_key(leaf: x509.Certificate) -> ec.EllipticCurvePublicKey:
    public_key = leaf.public_key()
    if not isinstance(public_key, ec.EllipticCurvePublicKey) or not isinstance(
        public_key.curve,
        ec.SECP256R1,
    ):
        raise MobileAuthError(MobileAuthFailure.ATTESTATION_PUBLIC_KEY_INVALID)
    return public_key


def _verify_key_identifier(public_key: ec.EllipticCurvePublicKey, key_id: str) -> None:
    point = public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    expected = base64.b64encode(hashlib.sha256(point).digest()).decode("ascii")
    if not secrets.compare_digest(key_id, expected):
        raise MobileAuthError(MobileAuthFailure.ATTESTATION_KEY_ID_MISMATCH)


def _parse_auth_data(auth_data: bytes) -> _AttestationAuthData:
    credential_flag = auth_data[_RP_ID_HASH_LENGTH] if len(auth_data) > _RP_ID_HASH_LENGTH else None
    if len(auth_data) < _AUTH_DATA_HEADER_LENGTH or credential_flag != _ATTESTED_CREDENTIAL_FLAG:
        raise MobileAuthError(MobileAuthFailure.ATTESTATION_AUTH_DATA_INVALID)
    credential_length = int.from_bytes(auth_data[53:55], "big")
    credential_end = _AUTH_DATA_HEADER_LENGTH + credential_length
    if credential_length != _CREDENTIAL_IDENTIFIER_LENGTH or credential_end >= len(auth_data):
        raise MobileAuthError(MobileAuthFailure.ATTESTATION_CREDENTIAL_DATA_INVALID)
    return _AttestationAuthData(
        rp_id_hash=auth_data[:_RP_ID_HASH_LENGTH],
        counter=int.from_bytes(auth_data[33:37], "big"),
        aaguid=auth_data[37:53],
        credential_id=auth_data[_AUTH_DATA_HEADER_LENGTH:credential_end],
        cose_key=auth_data[credential_end:],
    )


def _verify_auth_data(
    parsed: _AttestationAuthData,
    *,
    app_id: str,
    environment: str,
    key_id: str,
) -> None:
    expected_rp_id = hashlib.sha256(app_id.encode()).digest()
    if not secrets.compare_digest(parsed.rp_id_hash, expected_rp_id):
        raise MobileAuthError(MobileAuthFailure.ATTESTATION_APPLICATION_MISMATCH)
    if parsed.counter != 0:
        raise MobileAuthError(MobileAuthFailure.ATTESTATION_COUNTER_INVALID)
    expected_aaguid = DEVELOPMENT_AAGUID if environment == "development" else PRODUCTION_AAGUID
    if not secrets.compare_digest(parsed.aaguid, expected_aaguid):
        raise MobileAuthError(MobileAuthFailure.ATTESTATION_ENVIRONMENT_MISMATCH)
    key_id_bytes = decode_base64(key_id, maximum=64)
    if not secrets.compare_digest(parsed.credential_id, key_id_bytes):
        raise MobileAuthError(MobileAuthFailure.ATTESTATION_CREDENTIAL_MISMATCH)


def _verify_cose_key(raw: bytes, public_key: ec.EllipticCurvePublicKey) -> None:
    payload = decode_cbor(raw)
    if not isinstance(payload, dict):
        raise MobileAuthError(MobileAuthFailure.COSE_KEY_INVALID)
    numbers = public_key.public_numbers()
    expected: dict[int, int | bytes] = {
        1: 2,
        3: -7,
        -1: 1,
        -2: numbers.x.to_bytes(32, "big"),
        -3: numbers.y.to_bytes(32, "big"),
    }
    if payload != expected:
        raise MobileAuthError(MobileAuthFailure.COSE_KEY_MISMATCH)
