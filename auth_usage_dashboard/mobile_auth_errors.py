# Copyright (c) 2026 PitchAI. All rights reserved.
"""Stable, client-safe failures for native App Attest requests."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class FailureSpec:
    """One stable API error code and its non-sensitive explanation."""

    code: str
    detail: str


class MobileAuthFailure(Enum):
    """All fail-closed native-auth outcomes exposed to API clients."""

    INVALID_PURPOSE = FailureSpec("invalid_purpose", "Unsupported mobile request purpose")
    CHALLENGE_CAPACITY = FailureSpec(
        "challenge_capacity",
        "Mobile challenge capacity is temporarily exhausted",
    )
    CHALLENGE_INVALID = FailureSpec("challenge_invalid", "Mobile challenge is missing or expired")
    CHALLENGE_MISMATCH = FailureSpec("challenge_mismatch", "Mobile challenge does not match this request")
    KEY_ALREADY_REGISTERED = FailureSpec("key_already_registered", "This App Attest key is already registered")
    ENROLLMENT_CLOSED = FailureSpec("enrollment_closed", "New App Attest enrollment is closed")
    KEY_LIMIT = FailureSpec("key_limit", "The registered App Attest key limit is reached")
    KEY_UNKNOWN = FailureSpec("key_unknown", "App Attest key is not registered")
    KEY_INVALID = FailureSpec("key_invalid", "Stored App Attest key is invalid")
    ATTESTATION_OBJECT_INVALID = FailureSpec("attestation_invalid", "App Attest object is invalid")
    ATTESTATION_FORMAT_INVALID = FailureSpec("attestation_invalid", "App Attest format is invalid")
    ATTESTATION_STATEMENT_INVALID = FailureSpec("attestation_invalid", "App Attest statement is invalid")
    ATTESTATION_CERTIFICATE_INVALID = FailureSpec("attestation_invalid", "App Attest certificate is invalid")
    ATTESTATION_NONCE_MISSING = FailureSpec("attestation_invalid", "App Attest nonce is missing")
    ATTESTATION_NONCE_INVALID = FailureSpec("attestation_invalid", "App Attest nonce is invalid")
    ATTESTATION_NONCE_MISMATCH = FailureSpec("attestation_invalid", "App Attest nonce does not match")
    ATTESTATION_PUBLIC_KEY_INVALID = FailureSpec("attestation_invalid", "App Attest public key is invalid")
    ATTESTATION_KEY_ID_MISMATCH = FailureSpec(
        "attestation_invalid",
        "App Attest key identifier does not match",
    )
    ATTESTATION_APPLICATION_MISMATCH = FailureSpec(
        "attestation_invalid",
        "App Attest application does not match",
    )
    ATTESTATION_COUNTER_INVALID = FailureSpec("attestation_invalid", "App Attest counter is invalid")
    ATTESTATION_ENVIRONMENT_MISMATCH = FailureSpec(
        "attestation_invalid",
        "App Attest environment does not match",
    )
    ATTESTATION_CREDENTIAL_MISMATCH = FailureSpec(
        "attestation_invalid",
        "App Attest credential does not match",
    )
    ASSERTION_INVALID = FailureSpec("assertion_invalid", "App Attest assertion is invalid")
    ASSERTION_AUTH_DATA_INVALID = FailureSpec(
        "assertion_invalid",
        "App Attest authenticator data is invalid",
    )
    ASSERTION_FLAGS_INVALID = FailureSpec("assertion_flags_invalid", "App Attest assertion flags are invalid")
    ASSERTION_APPLICATION_MISMATCH = FailureSpec(
        "assertion_invalid",
        "App Attest application does not match",
    )
    ASSERTION_REPLAYED = FailureSpec("assertion_replayed", "App Attest assertion was already used")
    ASSERTION_SIGNATURE_INVALID = FailureSpec("assertion_invalid", "App Attest signature is invalid")
    CERTIFICATE_EXPIRED = FailureSpec("attestation_invalid", "App Attest certificate is expired")
    CERTIFICATE_CHAIN_INVALID = FailureSpec("attestation_invalid", "App Attest certificate chain is invalid")
    LEAF_CERTIFICATE_INVALID = FailureSpec("attestation_invalid", "App Attest leaf certificate is invalid")
    INTERMEDIATE_CERTIFICATE_INVALID = FailureSpec("attestation_invalid", "App Attest intermediate is invalid")
    ROOT_CERTIFICATE_INVALID = FailureSpec("attestation_invalid", "App Attest root is invalid")
    CERTIFICATE_CONSTRAINTS_MISSING = FailureSpec(
        "attestation_invalid",
        "App Attest certificate constraints are missing",
    )
    ISSUER_KEY_INVALID = FailureSpec("attestation_invalid", "App Attest issuer key is invalid")
    CERTIFICATE_SIGNATURE_INVALID = FailureSpec(
        "attestation_invalid",
        "App Attest certificate signature is invalid",
    )
    ATTESTATION_AUTH_DATA_INVALID = FailureSpec(
        "attestation_invalid",
        "App Attest authenticator data is invalid",
    )
    ATTESTATION_CREDENTIAL_DATA_INVALID = FailureSpec(
        "attestation_invalid",
        "App Attest credential data is invalid",
    )
    COSE_KEY_INVALID = FailureSpec("attestation_invalid", "App Attest COSE key is invalid")
    COSE_KEY_MISMATCH = FailureSpec("attestation_invalid", "App Attest COSE key does not match")
    NONCE_EXTENSION_INVALID = FailureSpec("attestation_invalid", "App Attest nonce extension is invalid")
    DER_VALUE_INVALID = FailureSpec("attestation_invalid", "App Attest DER value is invalid")
    DER_LENGTH_INVALID = FailureSpec("attestation_invalid", "App Attest DER length is invalid")
    DER_LENGTH_NONCANONICAL = FailureSpec("attestation_invalid", "App Attest DER length is noncanonical")
    DER_VALUE_TRUNCATED = FailureSpec("attestation_invalid", "App Attest DER value is truncated")
    CBOR_INVALID = FailureSpec("cbor_invalid", "App Attest CBOR is invalid")
    CBOR_TRAILING_DATA = FailureSpec("cbor_invalid", "App Attest CBOR has trailing data")
    BASE64_INVALID = FailureSpec("base64_invalid", "App Attest value is invalid")
    BASE64_MALFORMED = FailureSpec("base64_invalid", "App Attest value is not valid Base64")
    BASE64_SIZE_INVALID = FailureSpec("base64_invalid", "App Attest value has an invalid size")
    KEY_ID_INVALID = FailureSpec("key_id_invalid", "App Attest key identifier is invalid")


class MobileAuthError(Exception):
    """A stable native-auth failure safe to translate into an API response."""

    code: str
    detail: str

    def __init__(self, failure: MobileAuthFailure) -> None:
        """Initialize the failure from its canonical public specification."""
        self.code = failure.value.code
        self.detail = failure.value.detail
        super().__init__(self.detail)
