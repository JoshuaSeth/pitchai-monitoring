# Copyright (c) 2026 PitchAI. All rights reserved.
"""Security regression coverage for App Attest primitives and storage."""

from __future__ import annotations

import base64
import unittest
from typing import TYPE_CHECKING

from ._mobile_test_crypto import APP_ID, AttestationCryptoFixture
from ._mobile_test_fixtures import app_attest_registry
from ._mobile_test_runtime import RAISES
from ._timeseries_test_fixtures import check, check_equal, isolated_root
from .mobile_assertion import verify_assertion
from .mobile_auth_errors import MobileAuthError
from .mobile_challenges import ChallengeStore, canonical_client_data

if TYPE_CHECKING:
    from pathlib import Path

_SUPPORTED_FLAGS = (0x00, 0x40)
_REJECTED_FLAGS = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x41, 0x44, 0x80, 0xFF)


class MobileAuthCase(unittest.TestCase):
    """Exercise the fail-closed App Attest lifecycle."""

    root: Path
    crypto: AttestationCryptoFixture

    def setUp(self) -> None:
        """Create one isolated certificate chain and registry root."""
        self.root = self.enterContext(isolated_root())
        self.crypto = AttestationCryptoFixture(self.root)

    def test_registry_counter_and_private_persistence(self) -> None:
        """Advance counters once and keep durable registry material private."""
        registry = app_attest_registry(self.root, self.crypto)
        challenge = b"a" * 32
        registry.register(
            key_id=self.crypto.key_id,
            attestation_object=self.crypto.attestation(challenge),
            challenge=challenge,
        )
        client_data = b"canonical request"
        assertion = self.crypto.assertion(client_data, counter=1, flags=0x40)
        counter = registry.verify_assertion(
            key_id=self.crypto.key_id,
            assertion_object=assertion,
            client_data=client_data,
        )
        check_equal(counter, 1, "accepted assertion counter")
        with RAISES(MobileAuthError) as captured:
            _ = registry.verify_assertion(
                key_id=self.crypto.key_id,
                assertion_object=assertion,
                client_data=client_data,
            )
        check_equal(
            captured.value.code,
            "assertion_replayed",
            "replay failure code",
        )
        path = self.root / "mobile-app-attest.json"
        check_equal(path.stat().st_mode & 0o777, 0o600, "registry mode")
        persisted = path.read_text(encoding="utf-8")
        check("private-account" not in persisted, "registry excludes account canary")
        check("test-only" not in persisted, "registry excludes admin-token canary")

    def test_assertion_flags_follow_apple_contract(self) -> None:
        """Accept only the two Apple App Attest authenticator flag values."""
        client_data = b"canonical request"
        public_key = self.crypto.attested_key.public_key()
        for flags in _SUPPORTED_FLAGS:
            with self.subTest(flags=flags):
                counter = verify_assertion(
                    assertion_object=self.crypto.assertion(
                        client_data,
                        counter=1,
                        flags=flags,
                    ),
                    client_data=client_data,
                    app_id=APP_ID,
                    public_key=public_key,
                    previous_counter=0,
                )
                check_equal(counter, 1, "supported flag assertion counter")
        for flags in _REJECTED_FLAGS:
            with self.subTest(flags=flags):
                with RAISES(MobileAuthError) as captured:
                    _ = verify_assertion(
                        assertion_object=self.crypto.assertion(
                            client_data,
                            counter=1,
                            flags=flags,
                        ),
                        client_data=client_data,
                        app_id=APP_ID,
                        public_key=public_key,
                        previous_counter=0,
                    )
                check_equal(
                    captured.value.code,
                    "assertion_flags_invalid",
                    "unsupported flag failure code",
                )

    def test_attestation_is_bound_to_challenge_and_application(self) -> None:
        """Reject an attestation replayed against a different challenge."""
        registry = app_attest_registry(self.root, self.crypto)
        with RAISES(MobileAuthError) as captured:
            registry.register(
                key_id=self.crypto.key_id,
                attestation_object=self.crypto.attestation(b"a" * 32),
                challenge=b"b" * 32,
            )
        check_equal(
            captured.value.code,
            "attestation_invalid",
            "challenge-binding failure code",
        )

    def test_enrollment_is_closed_by_default_configuration(self) -> None:
        """Reject a new key before parsing attestation when enrollment is closed."""
        registry = app_attest_registry(
            self.root,
            self.crypto,
            enrollment_enabled=False,
        )
        with RAISES(MobileAuthError) as captured:
            registry.register(
                key_id=self.crypto.key_id,
                attestation_object="not-evaluated",
                challenge=b"a" * 32,
            )
        check_equal(
            captured.value.code,
            "enrollment_closed",
            "closed-enrollment failure code",
        )

    @staticmethod
    def test_challenges_are_key_bound_and_single_use() -> None:
        """Consume one canonical challenge once for its exact key and purpose."""
        store = ChallengeStore(ttl_seconds=120, max_pending=8)
        key_id = base64.b64encode(b"k" * 32).decode("ascii")
        challenge = store.issue(purpose="capacity", key_id=key_id)
        consumed = store.consume(
            identifier=challenge.identifier,
            purpose="capacity",
            key_id=key_id,
        )
        expected = (
            f"pitchai-codex-status-v1\ncapacity\n{challenge.identifier}\n{challenge.encoded_value}\n{key_id}"
        ).encode("ascii")
        check_equal(canonical_client_data(consumed), expected, "canonical client data")
        with RAISES(MobileAuthError) as captured:
            _ = store.consume(
                identifier=challenge.identifier,
                purpose="capacity",
                key_id=key_id,
            )
        check_equal(
            captured.value.code,
            "challenge_invalid",
            "single-use challenge failure code",
        )
