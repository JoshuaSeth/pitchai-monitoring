# Copyright (c) 2026 PitchAI. All rights reserved.
"""Deterministic-shape cryptographic fixtures for App Attest tests."""

from __future__ import annotations

import base64
import hashlib
import struct
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ObjectIdentifier

from ._mobile_test_cbor import CBOR_ENCODER

if TYPE_CHECKING:
    from pathlib import Path

    from .mobile_auth_codec import CborValue

APP_ID_PREFIX = "ZM6568G5FX"
BUNDLE_ID = "com.pitchai.codexstatus"
APP_ID = f"{APP_ID_PREFIX}.{BUNDLE_ID}"
_NONCE_OID = ObjectIdentifier("1.2.840.113635.100.8.2")


@dataclass(frozen=True)
class _CertificateAuthority:
    """One private-key and certificate pair in the fixture chain."""

    key: ec.EllipticCurvePrivateKey
    name: x509.Name
    certificate: x509.Certificate


@dataclass(frozen=True)
class _CertificateRequest:
    """Inputs for one bounded fixture certificate."""

    subject: x509.Name
    issuer: x509.Name
    public_key: ec.EllipticCurvePublicKey
    issuer_key: ec.EllipticCurvePrivateKey
    is_ca: bool
    now: datetime


class AttestationCryptoFixture:
    """Build one private test certificate chain and App Attest key."""

    root_authority: _CertificateAuthority
    intermediate_authority: _CertificateAuthority
    attested_key: ec.EllipticCurvePrivateKey
    key_id: str
    root_path: Path

    def __init__(self, root: Path) -> None:
        """Create the chain inside an isolated test root."""
        now = datetime.now(UTC)
        root_key = ec.generate_private_key(ec.SECP384R1())
        root_name = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "Test App Attest Root")],
        )
        root_certificate = self._certificate(
            _CertificateRequest(
                subject=root_name,
                issuer=root_name,
                public_key=root_key.public_key(),
                issuer_key=root_key,
                is_ca=True,
                now=now,
            ),
        )
        self.root_authority = _CertificateAuthority(
            root_key,
            root_name,
            root_certificate,
        )
        intermediate_key = ec.generate_private_key(ec.SECP384R1())
        intermediate_name = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "Test App Attest Intermediate")],
        )
        intermediate_certificate = self._certificate(
            _CertificateRequest(
                subject=intermediate_name,
                issuer=root_name,
                public_key=intermediate_key.public_key(),
                issuer_key=root_key,
                is_ca=True,
                now=now,
            ),
        )
        self.intermediate_authority = _CertificateAuthority(
            intermediate_key,
            intermediate_name,
            intermediate_certificate,
        )
        self.attested_key = ec.generate_private_key(ec.SECP256R1())
        point = self.attested_key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
        self.key_id = base64.b64encode(hashlib.sha256(point).digest()).decode("ascii")
        self.root_path = root / "test-app-attest-root.crt"
        _ = self.root_path.write_bytes(
            self.root_authority.certificate.public_bytes(serialization.Encoding.PEM),
        )

    def attestation(self, challenge: bytes, *, app_id: str = APP_ID) -> str:
        """Return one challenge- and application-bound attestation object."""
        credential = base64.b64decode(self.key_id)
        public_numbers = self.attested_key.public_key().public_numbers()
        cose: CborValue = {
            1: 2,
            3: -7,
            -1: 1,
            -2: public_numbers.x.to_bytes(32, "big"),
            -3: public_numbers.y.to_bytes(32, "big"),
        }
        auth_data = self._attestation_auth_data(
            app_id=app_id,
            credential=credential,
            cose=CBOR_ENCODER(cose),
        )
        leaf = self._leaf_certificate(auth_data, challenge)
        payload: CborValue = {
            "fmt": "apple-appattest",
            "attStmt": {
                "x5c": [
                    leaf.public_bytes(serialization.Encoding.DER),
                    self.intermediate_authority.certificate.public_bytes(
                        serialization.Encoding.DER,
                    ),
                ],
                "receipt": b"test-receipt",
            },
            "authData": auth_data,
        }
        return base64.b64encode(CBOR_ENCODER(payload)).decode("ascii")

    def assertion(self, client_data: bytes, *, counter: int, flags: int = 0) -> str:
        """Return one signed assertion for the fixture key."""
        auth_data = hashlib.sha256(APP_ID.encode()).digest() + bytes([flags]) + struct.pack(">I", counter)
        nonce = hashlib.sha256(
            auth_data + hashlib.sha256(client_data).digest(),
        ).digest()
        signature = self.attested_key.sign(nonce, ec.ECDSA(hashes.SHA256()))
        payload: CborValue = {
            "signature": signature,
            "authenticatorData": auth_data,
        }
        return base64.b64encode(CBOR_ENCODER(payload)).decode("ascii")

    @staticmethod
    def _attestation_auth_data(*, app_id: str, credential: bytes, cose: bytes) -> bytes:
        return (
            hashlib.sha256(app_id.encode()).digest()
            + b"\x40"
            + struct.pack(">I", 0)
            + b"appattestdevelop"
            + struct.pack(">H", len(credential))
            + credential
            + cose
        )

    def _leaf_certificate(self, auth_data: bytes, challenge: bytes) -> x509.Certificate:
        nonce = hashlib.sha256(auth_data + hashlib.sha256(challenge).digest()).digest()
        extension = b"\x30\x24\xa1\x22\x04\x20" + nonce
        now = datetime.now(UTC)
        leaf_name = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "Test App Attest Credential")],
        )
        return (
            x509
            .CertificateBuilder()
            .subject_name(leaf_name)
            .issuer_name(self.intermediate_authority.name)
            .public_key(self.attested_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=2))
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )
            .add_extension(
                x509.UnrecognizedExtension(_NONCE_OID, extension),
                critical=False,
            )
            .sign(self.intermediate_authority.key, hashes.SHA256())
        )

    @staticmethod
    def _certificate(request: _CertificateRequest) -> x509.Certificate:
        return (
            x509
            .CertificateBuilder()
            .subject_name(request.subject)
            .issuer_name(request.issuer)
            .public_key(request.public_key)
            .serial_number(x509.random_serial_number())
            .not_valid_before(request.now - timedelta(days=1))
            .not_valid_after(request.now + timedelta(days=30))
            .add_extension(
                x509.BasicConstraints(ca=request.is_ca, path_length=None),
                critical=True,
            )
            .sign(request.issuer_key, hashes.SHA256())
        )
