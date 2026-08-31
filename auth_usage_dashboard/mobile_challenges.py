# Copyright (c) 2026 PitchAI. All rights reserved.
"""Single-use challenges for the protected native-client API."""

from __future__ import annotations

import base64
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Literal

from .mobile_auth_codec import validate_key_id
from .mobile_auth_errors import MobileAuthError, MobileAuthFailure

type ChallengePurpose = Literal["attest", "capacity", "refresh"]


@dataclass(frozen=True)
class Challenge:
    """One short-lived challenge bound to a key and request purpose."""

    identifier: str
    value: bytes
    purpose: ChallengePurpose
    key_id: str
    created_monotonic: float

    @property
    def encoded_value(self) -> str:
        """Return the challenge bytes as canonical Base64."""
        return base64.b64encode(self.value).decode("ascii")


class ChallengeStore:
    """Issue and atomically consume bounded in-memory challenges."""

    ttl_seconds: int
    max_pending: int
    _lock: threading.Lock
    _pending: dict[str, Challenge]

    def __init__(self, *, ttl_seconds: int, max_pending: int) -> None:
        """Configure challenge lifetime and pending-request capacity."""
        self.ttl_seconds = ttl_seconds
        self.max_pending = max_pending
        self._lock = threading.Lock()
        self._pending = {}

    def issue(self, *, purpose: ChallengePurpose, key_id: str) -> Challenge:
        """Issue one challenge after validating its App Attest key binding.

        Returns:
            The new single-use challenge.

        Raises:
            MobileAuthError: If the key is invalid or capacity is exhausted.
        """
        validate_key_id(key_id)
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            if len(self._pending) >= self.max_pending:
                raise MobileAuthError(MobileAuthFailure.CHALLENGE_CAPACITY)
            challenge = Challenge(
                identifier=str(uuid.uuid4()),
                value=secrets.token_bytes(32),
                purpose=purpose,
                key_id=key_id,
                created_monotonic=now,
            )
            self._pending[challenge.identifier] = challenge
        return challenge

    def consume(
        self,
        *,
        identifier: str,
        purpose: ChallengePurpose,
        key_id: str,
    ) -> Challenge:
        """Consume one matching challenge exactly once.

        Returns:
            The consumed challenge.

        Raises:
            MobileAuthError: If it is missing, expired, or mismatched.
        """
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            challenge = self._pending.pop(identifier, None)
        if challenge is None:
            raise MobileAuthError(MobileAuthFailure.CHALLENGE_INVALID)
        if challenge.purpose != purpose or challenge.key_id != key_id:
            raise MobileAuthError(MobileAuthFailure.CHALLENGE_MISMATCH)
        return challenge

    def _prune_locked(self, now: float) -> None:
        pending_items = self._pending.items()
        expired_items = (item for item in pending_items if now - item[1].created_monotonic > self.ttl_seconds)
        expired_identifiers = (identifier for identifier, _challenge in expired_items)
        expired = tuple(expired_identifiers)
        for identifier in expired:
            _ = self._pending.pop(identifier, None)


def canonical_client_data(challenge: Challenge) -> bytes:
    """Return the versioned assertion message bound to one challenge."""
    return (
        "pitchai-codex-status-v1\n"
        f"{challenge.purpose}\n"
        f"{challenge.identifier}\n"
        f"{challenge.encoded_value}\n"
        f"{challenge.key_id}"
    ).encode("ascii")
