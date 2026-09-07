# Copyright (c) 2026 PitchAI. All rights reserved.
"""Fail-closed IO capture and single-attempt provider consumption."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast, final

from .clients import AccountScanError, BrokerProviderSource, RemoteCallError
from .guardian import NotificationError
from .models import ConsumeResult, PayloadError

if TYPE_CHECKING:
    from collections.abc import Callable

    from .models import AccountDescriptor, AccountObservation, ResetCredit
VALID_CONSUME_CODES = frozenset(
    {"reset", "nothing_to_reset", "no_credit", "already_redeemed"},
)


@dataclass(frozen=True)
class CapturedCall:
    """One completed IO call represented without local exception suppression."""

    value: list[AccountDescriptor] | AccountObservation | ConsumeResult | None
    error: BaseException | None


def capture_io(
    operation: Callable[
        [],
        list[AccountDescriptor] | AccountObservation | ConsumeResult,
    ],
) -> CapturedCall:
    """Execute an IO edge and expose its value or captured exception.

    Returns:
        A value-or-error record; exactly one field is populated.
    """
    with ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="reset-guardian-io",
    ) as executor:
        future = executor.submit(operation)
    error = future.exception()
    if error is not None:
        return CapturedCall(value=None, error=error)
    return CapturedCall(value=future.result(), error=None)


def safe_error_code(error: BaseException) -> str:
    """Reduce one captured failure to a credential-free audit code.

    Returns:
        A stable, secret-safe error code.
    """
    if isinstance(error, RemoteCallError):
        return f"{error.endpoint}:{error.error_code}"
    if isinstance(error, AccountScanError):
        return error.error_code
    if isinstance(error, PayloadError):
        return f"payload:{type(error).__name__}"
    if isinstance(error, NotificationError):
        return f"notification:{error.error_code}"
    return f"unexpected:{type(error).__name__}"


class SingleAttemptBrokerProviderSource(BrokerProviderSource):
    """Provider source that leaves every ambiguous retry to durable reconciliation."""

    @final
    def consume_credit(
        self,
        observation: AccountObservation,
        credit: ResetCredit,
        idempotency_key: str,
    ) -> ConsumeResult:
        """Issue exactly one targeted consume request for the durable logical key.

        Returns:
            The validated provider outcome.

        Raises:
            RuntimeError: The observation lacks broker-managed OAuth credentials.
            ValueError: The durable idempotency key is empty.
            RemoteCallError: The provider call or response validation is uncertain.
        """
        if observation.credentials is None:
            message = "live observation is missing OAuth credentials"
            raise RuntimeError(message)
        if not idempotency_key:
            message = "idempotency key must not be empty"
            raise ValueError(message)
        payload = {
            "redeem_request_id": idempotency_key,
            "credit_id": credit.provider_id,
        }
        endpoint = "provider_consume_reset_credit"
        consume_url = f"{self.provider_base_url}/wham/rate-limit-reset-credits/consume"
        provider_headers = self._provider_headers(observation.credentials)
        response = self.http.request(
            method="POST",
            url=consume_url,
            endpoint=endpoint,
            payload=payload,
            headers=provider_headers,
            ambiguous_on_failure=True,
        )
        raw_code = cast("object", response.get("code"))
        raw_windows = cast("object", response.get("windows_reset", 0))
        if not isinstance(raw_code, str) or raw_code not in VALID_CONSUME_CODES:
            raise RemoteCallError(
                endpoint="provider_consume_reset_credit",
                error_code="invalid_result_payload",
                ambiguous=True,
            )
        if (
            isinstance(raw_windows, bool)
            or not isinstance(raw_windows, int)
            or raw_windows < 0
        ):
            raise RemoteCallError(
                endpoint="provider_consume_reset_credit",
                error_code="invalid_result_payload",
                ambiguous=True,
            )
        return ConsumeResult(code=raw_code, windows_reset=raw_windows)
