# Copyright (c) 2026 PitchAI. All rights reserved.
"""Provider-edge proof that ambiguous consumes are never retried inline."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from functools import partial
from typing import final
from uuid import uuid4

from .clients import RemoteCallError
from .models import ProviderCredentials
from .organization_io import SingleAttemptBrokerProviderSource, capture_io
from .test_organization_support import (
    NOW,
    account_observation,
    require,
    require_equal,
    reset_credit,
)


@final
class AmbiguousTransport:
    """HTTP double that loses exactly one targeted provider response."""

    def __init__(self) -> None:
        """Start with no calls or captured target."""
        self._calls = 0
        self._target: tuple[str | None, str | None] | None = None

    def request(
        self,
        **arguments: str | bool | dict[str, str] | None,
    ) -> dict[str, str | int]:
        """Capture the target and raise one ambiguous transport result.

        Raises:
            RemoteCallError: Every request models a lost provider response.
        """
        self._calls += 1
        raw_payload = arguments.get("payload")
        if isinstance(raw_payload, dict):
            self._target = (
                raw_payload.get("credit_id"),
                raw_payload.get("redeem_request_id"),
            )
        raise RemoteCallError(
            endpoint="provider_consume_reset_credit",
            error_code="transport_timeout",
            ambiguous=True,
        )

    def request_count(self) -> int:
        """Return the number of attempted HTTP requests."""
        return self._calls

    def target(self) -> tuple[str | None, str | None] | None:
        """Return the captured exact credit and durable key."""
        return self._target


def test_ambiguous_provider_response_has_one_targeted_http_attempt() -> None:
    """Leave an uncertain retry to SQLite-backed restart reconciliation."""
    credit = reset_credit("opaque-single-attempt", expires_at=NOW + timedelta(days=10))
    observation = replace(
        account_observation("elise@pitchai.net", credit_bank=(credit,)),
        credentials=ProviderCredentials(
            access_token=uuid4().hex,
            account_id="test-account-id",
        ),
    )
    transport = AmbiguousTransport()
    source = SingleAttemptBrokerProviderSource(
        broker_url="http://broker.invalid",
        broker_admin_token=uuid4().hex,
        http=transport,
    )
    idempotency_key = "durable-test-key"
    consume = partial(source.consume_credit, observation, credit, idempotency_key)
    consumed = capture_io(consume)
    error = consumed.error

    require(
        condition=isinstance(error, RemoteCallError),
        message="ambiguous response did not fail closed",
    )
    if not isinstance(error, RemoteCallError):
        return
    require(condition=error.ambiguous, message="transport ambiguity was lost")
    require_equal(transport.request_count(), 1)
    require_equal(transport.target(), (credit.provider_id, idempotency_key))
