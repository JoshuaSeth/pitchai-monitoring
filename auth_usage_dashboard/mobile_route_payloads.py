# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict JSON request payloads for the protected native-client routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .mobile_challenges import ChallengePurpose
    from .timeseries_types import JsonObject


class RequestPayloadError(ValueError):
    """A native API request does not match its closed JSON schema."""


@dataclass(frozen=True)
class ChallengePayload:
    """Validated challenge request."""

    purpose: ChallengePurpose
    key_id: str


@dataclass(frozen=True)
class AttestationPayload:
    """Validated key-enrollment request."""

    challenge_id: str
    key_id: str
    attestation: str


@dataclass(frozen=True)
class AssertionPayload:
    """Validated protected-capacity or refresh request."""

    challenge_id: str
    key_id: str
    assertion: str


def parse_challenge(payload: JsonObject) -> ChallengePayload:
    """Validate one challenge request.

    Returns:
        The closed typed payload.

    Raises:
        RequestPayloadError: If fields are missing, extra, or invalid.
    """
    _require_exact_fields(payload, {"purpose", "key_id"})
    purpose = payload.get("purpose")
    if purpose == "attest":
        validated_purpose: ChallengePurpose = "attest"
    elif purpose == "capacity":
        validated_purpose = "capacity"
    elif purpose == "refresh":
        validated_purpose = "refresh"
    else:
        raise RequestPayloadError
    return ChallengePayload(
        purpose=validated_purpose,
        key_id=_required_text(payload, "key_id", minimum=40, maximum=128),
    )


def parse_attestation(payload: JsonObject) -> AttestationPayload:
    """Validate one enrollment request.

    Returns:
        The closed typed payload.
    """
    _require_exact_fields(payload, {"challenge_id", "key_id", "attestation"})
    return AttestationPayload(
        challenge_id=_required_text(payload, "challenge_id", minimum=36, maximum=36),
        key_id=_required_text(payload, "key_id", minimum=40, maximum=128),
        attestation=_required_text(payload, "attestation", minimum=1, maximum=131_072),
    )


def parse_assertion(payload: JsonObject) -> AssertionPayload:
    """Validate one assertion request.

    Returns:
        The closed typed payload.
    """
    _require_exact_fields(payload, {"challenge_id", "key_id", "assertion"})
    return AssertionPayload(
        challenge_id=_required_text(payload, "challenge_id", minimum=36, maximum=36),
        key_id=_required_text(payload, "key_id", minimum=40, maximum=128),
        assertion=_required_text(payload, "assertion", minimum=1, maximum=32_768),
    )


def _required_text(
    payload: JsonObject,
    key: str,
    *,
    minimum: int,
    maximum: int,
) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise RequestPayloadError
    return value


def _require_exact_fields(payload: JsonObject, expected: set[str]) -> None:
    if set(payload) != expected:
        raise RequestPayloadError
