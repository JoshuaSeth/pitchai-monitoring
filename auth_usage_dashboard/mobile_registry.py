# Copyright (c) 2026 PitchAI. All rights reserved.
"""Private registry and verification lifecycle for App Attest keys."""

from __future__ import annotations

import base64
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .mobile_assertion import verify_assertion
from .mobile_attestation import AttestationRequest, verify_attestation
from .mobile_auth_codec import validate_key_id
from .mobile_auth_errors import MobileAuthError, MobileAuthFailure
from .mobile_registry_storage import RegisteredKey, load_registry, persist_registry

if TYPE_CHECKING:
    from pathlib import Path

    from .mobile_registry_storage import AppAttestEnvironment


@dataclass(frozen=True)
class RegistryConfiguration:
    """Validated immutable registry and Apple application settings."""

    path: Path
    root_certificate_path: Path
    app_id: str
    environment: AppAttestEnvironment
    max_keys: int
    enrollment_enabled: bool = False


class AppAttestRegistry:
    """Verify App Attest requests and atomically persist enrolled keys."""

    configuration: RegistryConfiguration
    _lock: threading.Lock
    _root: x509.Certificate
    _keys: dict[str, RegisteredKey]

    def __init__(self, configuration: RegistryConfiguration) -> None:
        """Load one private registry with its pinned Apple root certificate."""
        self.configuration = configuration
        self._lock = threading.Lock()
        root_bytes = configuration.root_certificate_path.read_bytes()
        self._root = x509.load_pem_x509_certificate(root_bytes)
        self._keys = load_registry(configuration.path)

    @property
    def enrollment_enabled(self) -> bool:
        """Return whether this process may add previously unknown keys."""
        return self.configuration.enrollment_enabled

    def has_key(self, key_id: str) -> bool:
        """Return whether a validated App Attest key is enrolled."""
        validate_key_id(key_id)
        with self._lock:
            return key_id in self._keys

    def register(
        self,
        *,
        key_id: str,
        attestation_object: str,
        challenge: bytes,
    ) -> None:
        """Verify and persist one previously unknown App Attest key."""
        validate_key_id(key_id)
        with self._lock:
            self._require_enrollment_capacity(key_id)
            public_key, receipt = verify_attestation(
                AttestationRequest(
                    attestation_object=attestation_object,
                    key_id=key_id,
                    challenge=challenge,
                    app_id=self.configuration.app_id,
                    environment=self.configuration.environment,
                    root_certificate=self._root,
                ),
            )
            self._keys[key_id] = RegisteredKey(
                public_key_pem=public_key.public_bytes(
                    serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                ).decode("ascii"),
                receipt=base64.b64encode(receipt).decode("ascii"),
                environment=self.configuration.environment,
                registered_at=_iso_now(),
            )
            persist_registry(self.configuration.path, self._keys)

    def verify_assertion(
        self,
        *,
        key_id: str,
        assertion_object: str,
        client_data: bytes,
    ) -> int:
        """Verify, advance, and durably persist one assertion counter.

        Returns:
            The new monotonic assertion counter.

        Raises:
            MobileAuthError: If the key or assertion is invalid.
        """
        validate_key_id(key_id)
        with self._lock:
            stored = self._keys.get(key_id)
            if stored is None:
                raise MobileAuthError(MobileAuthFailure.KEY_UNKNOWN)
            public_key = serialization.load_pem_public_key(stored.public_key_pem.encode())
            if not isinstance(public_key, ec.EllipticCurvePublicKey):
                raise MobileAuthError(MobileAuthFailure.KEY_INVALID)
            counter = verify_assertion(
                assertion_object=assertion_object,
                client_data=client_data,
                app_id=self.configuration.app_id,
                public_key=public_key,
                previous_counter=stored.last_counter,
            )
            stored.last_counter = counter
            stored.last_verified_at = _iso_now()
            persist_registry(self.configuration.path, self._keys)
        return counter

    def _require_enrollment_capacity(self, key_id: str) -> None:
        if key_id in self._keys:
            raise MobileAuthError(MobileAuthFailure.KEY_ALREADY_REGISTERED)
        if not self.enrollment_enabled:
            raise MobileAuthError(MobileAuthFailure.ENROLLMENT_CLOSED)
        if len(self._keys) >= self.configuration.max_keys:
            raise MobileAuthError(MobileAuthFailure.KEY_LIMIT)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
