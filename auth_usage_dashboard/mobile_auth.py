from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
import secrets
import struct
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cbor2
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtensionOID, ObjectIdentifier


UTC = timezone.utc
NONCE_EXTENSION_OID = ObjectIdentifier("1.2.840.113635.100.8.2")
DEVELOPMENT_AAGUID = b"appattestdevelop"
PRODUCTION_AAGUID = b"appattest" + (b"\x00" * 7)
ALLOWED_PURPOSES = frozenset({"attest", "capacity", "refresh"})
MAX_KEY_ID_BYTES = 128
MAX_ATTESTATION_BYTES = 64 * 1024
MAX_ASSERTION_BYTES = 16 * 1024


class MobileAuthError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Challenge:
    identifier: str
    value: bytes
    purpose: str
    key_id: str
    created_monotonic: float

    @property
    def encoded_value(self) -> str:
        return base64.b64encode(self.value).decode("ascii")


class ChallengeStore:
    def __init__(self, *, ttl_seconds: int, max_pending: int) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_pending = max_pending
        self._lock = threading.Lock()
        self._pending: dict[str, Challenge] = {}

    def issue(self, *, purpose: str, key_id: str) -> Challenge:
        if purpose not in ALLOWED_PURPOSES:
            raise MobileAuthError("invalid_purpose", "Unsupported mobile request purpose")
        _validate_key_id(key_id)
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            if len(self._pending) >= self.max_pending:
                raise MobileAuthError(
                    "challenge_capacity",
                    "Mobile challenge capacity is temporarily exhausted",
                )
            challenge = Challenge(
                identifier=str(uuid.uuid4()),
                value=secrets.token_bytes(32),
                purpose=purpose,
                key_id=key_id,
                created_monotonic=now,
            )
            self._pending[challenge.identifier] = challenge
            return challenge

    def consume(self, *, identifier: str, purpose: str, key_id: str) -> Challenge:
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            challenge = self._pending.pop(identifier, None)
        if challenge is None:
            raise MobileAuthError(
                "challenge_invalid", "Mobile challenge is missing or expired"
            )
        if challenge.purpose != purpose or challenge.key_id != key_id:
            raise MobileAuthError(
                "challenge_mismatch", "Mobile challenge does not match this request"
            )
        return challenge

    def _prune_locked(self, now: float) -> None:
        expired = [
            identifier
            for identifier, challenge in self._pending.items()
            if now - challenge.created_monotonic > self.ttl_seconds
        ]
        for identifier in expired:
            self._pending.pop(identifier, None)


class AppAttestRegistry:
    def __init__(
        self,
        *,
        path: Path,
        root_certificate_path: Path,
        app_id: str,
        environment: str,
        max_keys: int,
        enrollment_enabled: bool,
    ) -> None:
        if environment not in {"development", "production"}:
            raise RuntimeError("App Attest environment must be development or production")
        self.path = path
        self.app_id = app_id
        self.environment = environment
        self.max_keys = max_keys
        self.enrollment_enabled = enrollment_enabled
        self._lock = threading.Lock()
        self._root = x509.load_pem_x509_certificate(root_certificate_path.read_bytes())
        self._payload = self._load()

    def has_key(self, key_id: str) -> bool:
        _validate_key_id(key_id)
        with self._lock:
            return key_id in self._payload["keys"]

    def register(
        self,
        *,
        key_id: str,
        attestation_object: str,
        challenge: bytes,
    ) -> None:
        _validate_key_id(key_id)
        with self._lock:
            existing = self._payload["keys"].get(key_id)
            if existing is not None:
                raise MobileAuthError(
                    "key_already_registered",
                    "This App Attest key is already registered",
                )
            if not self.enrollment_enabled:
                raise MobileAuthError(
                    "enrollment_closed", "New App Attest enrollment is closed"
                )
            if len(self._payload["keys"]) >= self.max_keys:
                raise MobileAuthError(
                    "key_limit", "The registered App Attest key limit is reached"
                )
            public_key, receipt = verify_attestation(
                attestation_object=attestation_object,
                key_id=key_id,
                challenge=challenge,
                app_id=self.app_id,
                environment=self.environment,
                root_certificate=self._root,
            )
            self._payload["keys"][key_id] = {
                "public_key_pem": public_key.public_bytes(
                    serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                ).decode("ascii"),
                "receipt": base64.b64encode(receipt).decode("ascii"),
                "environment": self.environment,
                "registered_at": _iso_now(),
                "last_counter": 0,
            }
            self._persist_locked()

    def verify_assertion(
        self,
        *,
        key_id: str,
        assertion_object: str,
        client_data: bytes,
    ) -> int:
        _validate_key_id(key_id)
        with self._lock:
            stored = self._payload["keys"].get(key_id)
            if not isinstance(stored, dict):
                raise MobileAuthError("key_unknown", "App Attest key is not registered")
            public_key = serialization.load_pem_public_key(
                stored["public_key_pem"].encode("ascii")
            )
            if not isinstance(public_key, ec.EllipticCurvePublicKey):
                raise MobileAuthError("key_invalid", "Stored App Attest key is invalid")
            counter = verify_assertion(
                assertion_object=assertion_object,
                client_data=client_data,
                app_id=self.app_id,
                public_key=public_key,
                previous_counter=int(stored.get("last_counter", 0)),
            )
            stored["last_counter"] = counter
            stored["last_verified_at"] = _iso_now()
            self._persist_locked()
            return counter

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": 1, "keys": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("App Attest registry is unreadable") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != 1
            or not isinstance(payload.get("keys"), dict)
        ):
            raise RuntimeError("App Attest registry schema is invalid")
        return payload

    def _persist_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        serialized = json.dumps(
            self._payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            directory_descriptor = os.open(self.path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            if temporary.exists():
                temporary.unlink()


def canonical_client_data(challenge: Challenge) -> bytes:
    return (
        "pitchai-codex-status-v1\n"
        f"{challenge.purpose}\n"
        f"{challenge.identifier}\n"
        f"{challenge.encoded_value}\n"
        f"{challenge.key_id}"
    ).encode("ascii")


def verify_attestation(
    *,
    attestation_object: str,
    key_id: str,
    challenge: bytes,
    app_id: str,
    environment: str,
    root_certificate: x509.Certificate,
) -> tuple[ec.EllipticCurvePublicKey, bytes]:
    raw = _decode_base64(attestation_object, maximum=MAX_ATTESTATION_BYTES)
    payload = _decode_cbor(raw)
    if not isinstance(payload, dict) or set(payload) != {"fmt", "attStmt", "authData"}:
        raise MobileAuthError("attestation_invalid", "App Attest object is invalid")
    if payload.get("fmt") != "apple-appattest":
        raise MobileAuthError("attestation_invalid", "App Attest format is invalid")
    statement = payload.get("attStmt")
    auth_data = payload.get("authData")
    if not isinstance(statement, dict) or not isinstance(auth_data, bytes):
        raise MobileAuthError("attestation_invalid", "App Attest object is invalid")
    if set(statement) != {"x5c", "receipt"}:
        raise MobileAuthError("attestation_invalid", "App Attest statement is invalid")
    certificate_data = statement.get("x5c")
    receipt = statement.get("receipt")
    if (
        not isinstance(certificate_data, list)
        or len(certificate_data) != 2
        or not all(isinstance(item, bytes) for item in certificate_data)
        or not isinstance(receipt, bytes)
        or not receipt
    ):
        raise MobileAuthError("attestation_invalid", "App Attest statement is invalid")
    try:
        leaf = x509.load_der_x509_certificate(certificate_data[0])
        intermediate = x509.load_der_x509_certificate(certificate_data[1])
    except ValueError as exc:
        raise MobileAuthError("attestation_invalid", "App Attest certificate is invalid") from exc
    _verify_certificate_chain(leaf, intermediate, root_certificate)

    expected_nonce = hashlib.sha256(
        auth_data + hashlib.sha256(challenge).digest()
    ).digest()
    try:
        extension = leaf.extensions.get_extension_for_oid(NONCE_EXTENSION_OID)
    except x509.ExtensionNotFound as exc:
        raise MobileAuthError("attestation_invalid", "App Attest nonce is missing") from exc
    if not isinstance(extension.value, x509.UnrecognizedExtension):
        raise MobileAuthError("attestation_invalid", "App Attest nonce is invalid")
    if not secrets.compare_digest(_decode_nonce_extension(extension.value.value), expected_nonce):
        raise MobileAuthError("attestation_invalid", "App Attest nonce does not match")

    public_key = leaf.public_key()
    if not isinstance(public_key, ec.EllipticCurvePublicKey) or not isinstance(
        public_key.curve, ec.SECP256R1
    ):
        raise MobileAuthError("attestation_invalid", "App Attest public key is invalid")
    public_point = public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    expected_key_id = base64.b64encode(hashlib.sha256(public_point).digest()).decode(
        "ascii"
    )
    if not secrets.compare_digest(key_id, expected_key_id):
        raise MobileAuthError("attestation_invalid", "App Attest key identifier does not match")

    parsed = _parse_attestation_auth_data(auth_data)
    expected_rp_id = hashlib.sha256(app_id.encode("utf-8")).digest()
    if not secrets.compare_digest(parsed["rp_id_hash"], expected_rp_id):
        raise MobileAuthError("attestation_invalid", "App Attest application does not match")
    if parsed["counter"] != 0:
        raise MobileAuthError("attestation_invalid", "App Attest counter is invalid")
    expected_aaguid = (
        DEVELOPMENT_AAGUID if environment == "development" else PRODUCTION_AAGUID
    )
    if not secrets.compare_digest(parsed["aaguid"], expected_aaguid):
        raise MobileAuthError("attestation_invalid", "App Attest environment does not match")
    key_id_bytes = _decode_base64(key_id, maximum=64)
    if not secrets.compare_digest(parsed["credential_id"], key_id_bytes):
        raise MobileAuthError("attestation_invalid", "App Attest credential does not match")
    _verify_cose_key(parsed["cose_key"], public_key)
    return public_key, receipt


def verify_assertion(
    *,
    assertion_object: str,
    client_data: bytes,
    app_id: str,
    public_key: ec.EllipticCurvePublicKey,
    previous_counter: int,
) -> int:
    raw = _decode_base64(assertion_object, maximum=MAX_ASSERTION_BYTES)
    payload = _decode_cbor(raw)
    if not isinstance(payload, dict) or set(payload) != {
        "signature",
        "authenticatorData",
    }:
        raise MobileAuthError("assertion_invalid", "App Attest assertion is invalid")
    signature = payload.get("signature")
    auth_data = payload.get("authenticatorData")
    if not isinstance(signature, bytes) or not isinstance(auth_data, bytes):
        raise MobileAuthError("assertion_invalid", "App Attest assertion is invalid")
    if len(auth_data) != 37:
        raise MobileAuthError("assertion_invalid", "App Attest authenticator data is invalid")
    rp_id_hash = auth_data[:32]
    counter = struct.unpack(">I", auth_data[33:37])[0]
    if auth_data[32] != 0:
        raise MobileAuthError("assertion_invalid", "App Attest assertion flags are invalid")
    expected_rp_id = hashlib.sha256(app_id.encode("utf-8")).digest()
    if not secrets.compare_digest(rp_id_hash, expected_rp_id):
        raise MobileAuthError("assertion_invalid", "App Attest application does not match")
    if counter <= previous_counter:
        raise MobileAuthError("assertion_replayed", "App Attest assertion was already used")
    nonce = hashlib.sha256(auth_data + hashlib.sha256(client_data).digest()).digest()
    try:
        public_key.verify(signature, nonce, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise MobileAuthError("assertion_invalid", "App Attest signature is invalid") from exc
    return counter


def _verify_certificate_chain(
    leaf: x509.Certificate,
    intermediate: x509.Certificate,
    root: x509.Certificate,
) -> None:
    now = datetime.now(UTC)
    for certificate in (leaf, intermediate, root):
        if not certificate.not_valid_before_utc <= now <= certificate.not_valid_after_utc:
            raise MobileAuthError("attestation_invalid", "App Attest certificate is expired")
    if leaf.issuer != intermediate.subject or intermediate.issuer != root.subject:
        raise MobileAuthError("attestation_invalid", "App Attest certificate chain is invalid")
    _verify_certificate_signature(leaf, intermediate)
    _verify_certificate_signature(intermediate, root)
    try:
        if leaf.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value.ca:
            raise MobileAuthError("attestation_invalid", "App Attest leaf certificate is invalid")
        if not intermediate.extensions.get_extension_for_oid(
            ExtensionOID.BASIC_CONSTRAINTS
        ).value.ca:
            raise MobileAuthError("attestation_invalid", "App Attest intermediate is invalid")
        if not root.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value.ca:
            raise MobileAuthError("attestation_invalid", "App Attest root is invalid")
    except x509.ExtensionNotFound as exc:
        raise MobileAuthError("attestation_invalid", "App Attest certificate constraints are missing") from exc


def _verify_certificate_signature(
    certificate: x509.Certificate, issuer: x509.Certificate
) -> None:
    issuer_key = issuer.public_key()
    if not isinstance(issuer_key, ec.EllipticCurvePublicKey):
        raise MobileAuthError("attestation_invalid", "App Attest issuer key is invalid")
    try:
        issuer_key.verify(
            certificate.signature,
            certificate.tbs_certificate_bytes,
            ec.ECDSA(certificate.signature_hash_algorithm),
        )
    except InvalidSignature as exc:
        raise MobileAuthError("attestation_invalid", "App Attest certificate signature is invalid") from exc


def _parse_attestation_auth_data(auth_data: bytes) -> dict[str, Any]:
    if len(auth_data) < 55 or auth_data[32] != 0x40:
        raise MobileAuthError("attestation_invalid", "App Attest authenticator data is invalid")
    credential_length = struct.unpack(">H", auth_data[53:55])[0]
    credential_end = 55 + credential_length
    if credential_length != 32 or credential_end >= len(auth_data):
        raise MobileAuthError("attestation_invalid", "App Attest credential data is invalid")
    return {
        "rp_id_hash": auth_data[:32],
        "counter": struct.unpack(">I", auth_data[33:37])[0],
        "aaguid": auth_data[37:53],
        "credential_id": auth_data[55:credential_end],
        "cose_key": auth_data[credential_end:],
    }


def _verify_cose_key(raw: bytes, public_key: ec.EllipticCurvePublicKey) -> None:
    payload = _decode_cbor(raw)
    if not isinstance(payload, dict):
        raise MobileAuthError("attestation_invalid", "App Attest COSE key is invalid")
    numbers = public_key.public_numbers()
    expected = {
        1: 2,
        3: -7,
        -1: 1,
        -2: numbers.x.to_bytes(32, "big"),
        -3: numbers.y.to_bytes(32, "big"),
    }
    if payload != expected:
        raise MobileAuthError("attestation_invalid", "App Attest COSE key does not match")


def _decode_nonce_extension(raw: bytes) -> bytes:
    sequence, offset = _read_der_value(raw, 0x30, 0)
    if offset != len(raw):
        raise MobileAuthError("attestation_invalid", "App Attest nonce extension is invalid")
    contextual, offset = _read_der_value(sequence, 0xA1, 0)
    if offset != len(sequence):
        raise MobileAuthError("attestation_invalid", "App Attest nonce extension is invalid")
    nonce, offset = _read_der_value(contextual, 0x04, 0)
    if offset != len(contextual) or len(nonce) != 32:
        raise MobileAuthError("attestation_invalid", "App Attest nonce extension is invalid")
    return nonce


def _read_der_value(raw: bytes, expected_tag: int, offset: int) -> tuple[bytes, int]:
    if offset >= len(raw) or raw[offset] != expected_tag:
        raise MobileAuthError("attestation_invalid", "App Attest DER value is invalid")
    offset += 1
    if offset >= len(raw):
        raise MobileAuthError("attestation_invalid", "App Attest DER length is invalid")
    first = raw[offset]
    offset += 1
    if first & 0x80:
        count = first & 0x7F
        if count == 0 or count > 4 or offset + count > len(raw):
            raise MobileAuthError("attestation_invalid", "App Attest DER length is invalid")
        length = int.from_bytes(raw[offset : offset + count], "big")
        if length < 128:
            raise MobileAuthError("attestation_invalid", "App Attest DER length is noncanonical")
        offset += count
    else:
        length = first
    end = offset + length
    if end > len(raw):
        raise MobileAuthError("attestation_invalid", "App Attest DER value is truncated")
    return raw[offset:end], end


def _decode_cbor(raw: bytes) -> Any:
    stream = io.BytesIO(raw)
    try:
        payload = cbor2.CBORDecoder(stream).decode()
    except (cbor2.CBORDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise MobileAuthError("cbor_invalid", "App Attest CBOR is invalid") from exc
    if stream.read(1):
        raise MobileAuthError("cbor_invalid", "App Attest CBOR has trailing data")
    return payload


def _decode_base64(value: str, *, maximum: int) -> bytes:
    if not isinstance(value, str) or not value or len(value) > maximum * 2:
        raise MobileAuthError("base64_invalid", "App Attest value is invalid")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MobileAuthError("base64_invalid", "App Attest value is not valid Base64") from exc
    if not decoded or len(decoded) > maximum:
        raise MobileAuthError("base64_invalid", "App Attest value has an invalid size")
    return decoded


def _validate_key_id(key_id: str) -> None:
    if not isinstance(key_id, str) or not 1 <= len(key_id) <= MAX_KEY_ID_BYTES:
        raise MobileAuthError("key_id_invalid", "App Attest key identifier is invalid")
    decoded = _decode_base64(key_id, maximum=64)
    if len(decoded) != 32:
        raise MobileAuthError("key_id_invalid", "App Attest key identifier is invalid")


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
