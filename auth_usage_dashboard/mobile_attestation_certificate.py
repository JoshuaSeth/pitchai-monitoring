# Copyright (c) 2026 PitchAI. All rights reserved.
"""Certificate and DER verification for Apple App Attest."""

from __future__ import annotations

from datetime import UTC, datetime

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtensionOID

from .mobile_auth_errors import MobileAuthError, MobileAuthFailure

_NONCE_LENGTH = 32
_MAX_DER_LENGTH_BYTES = 4
_DER_LONG_FORM_THRESHOLD = 128


def verify_certificate_chain(
    leaf: x509.Certificate,
    intermediate: x509.Certificate,
    root: x509.Certificate,
) -> None:
    """Verify the bounded EC certificate chain used by App Attest.

    Raises:
        MobileAuthError: If validity, identity, constraints, or signatures fail.
    """
    now = datetime.now(UTC)
    for certificate in (leaf, intermediate, root):
        if not certificate.not_valid_before_utc <= now <= certificate.not_valid_after_utc:
            raise MobileAuthError(MobileAuthFailure.CERTIFICATE_EXPIRED)
    if leaf.issuer != intermediate.subject or intermediate.issuer != root.subject:
        raise MobileAuthError(MobileAuthFailure.CERTIFICATE_CHAIN_INVALID)
    _verify_certificate_signature(leaf, intermediate)
    _verify_certificate_signature(intermediate, root)
    if _basic_constraints(leaf).ca:
        raise MobileAuthError(MobileAuthFailure.LEAF_CERTIFICATE_INVALID)
    if not _basic_constraints(intermediate).ca:
        raise MobileAuthError(MobileAuthFailure.INTERMEDIATE_CERTIFICATE_INVALID)
    if not _basic_constraints(root).ca:
        raise MobileAuthError(MobileAuthFailure.ROOT_CERTIFICATE_INVALID)


def decode_nonce_extension(raw: bytes) -> bytes:
    """Decode Apple's nested DER nonce extension.

    Returns:
        The exact 32-byte nonce.

    Raises:
        MobileAuthError: If the extension is malformed or noncanonical.
    """
    sequence, sequence_end = _read_der_value(raw, expected_tag=0x30, offset=0)
    if sequence_end != len(raw):
        raise MobileAuthError(MobileAuthFailure.NONCE_EXTENSION_INVALID)
    contextual, contextual_end = _read_der_value(sequence, expected_tag=0xA1, offset=0)
    if contextual_end != len(sequence):
        raise MobileAuthError(MobileAuthFailure.NONCE_EXTENSION_INVALID)
    nonce, nonce_end = _read_der_value(contextual, expected_tag=0x04, offset=0)
    if nonce_end != len(contextual) or len(nonce) != _NONCE_LENGTH:
        raise MobileAuthError(MobileAuthFailure.NONCE_EXTENSION_INVALID)
    return nonce


def _verify_certificate_signature(
    certificate: x509.Certificate,
    issuer: x509.Certificate,
) -> None:
    issuer_key = issuer.public_key()
    if not isinstance(issuer_key, ec.EllipticCurvePublicKey):
        raise MobileAuthError(MobileAuthFailure.ISSUER_KEY_INVALID)
    signature_hash = certificate.signature_hash_algorithm
    if signature_hash is None:
        raise MobileAuthError(MobileAuthFailure.CERTIFICATE_SIGNATURE_INVALID)
    issuer_key.verify(
        certificate.signature,
        certificate.tbs_certificate_bytes,
        ec.ECDSA(signature_hash),
    )


def _basic_constraints(certificate: x509.Certificate) -> x509.BasicConstraints:
    value = certificate.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value
    if not isinstance(value, x509.BasicConstraints):
        raise MobileAuthError(MobileAuthFailure.CERTIFICATE_CONSTRAINTS_MISSING)
    return value


def _read_der_value(
    raw: bytes,
    *,
    expected_tag: int,
    offset: int,
) -> tuple[bytes, int]:
    if offset >= len(raw) or raw[offset] != expected_tag:
        raise MobileAuthError(MobileAuthFailure.DER_VALUE_INVALID)
    value_offset = offset + 1
    if value_offset >= len(raw):
        raise MobileAuthError(MobileAuthFailure.DER_LENGTH_INVALID)
    first = raw[value_offset]
    value_offset += 1
    if first & 0x80:
        count = first & 0x7F
        if count == 0 or count > _MAX_DER_LENGTH_BYTES or value_offset + count > len(raw):
            raise MobileAuthError(MobileAuthFailure.DER_LENGTH_INVALID)
        length = int.from_bytes(raw[value_offset : value_offset + count], "big")
        if length < _DER_LONG_FORM_THRESHOLD:
            raise MobileAuthError(MobileAuthFailure.DER_LENGTH_NONCANONICAL)
        value_offset += count
    else:
        length = first
    end = value_offset + length
    if end > len(raw):
        raise MobileAuthError(MobileAuthFailure.DER_VALUE_TRUNCATED)
    return raw[value_offset:end], end
