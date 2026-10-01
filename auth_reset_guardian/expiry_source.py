# Copyright (c) 2026 PitchAI. All rights reserved.
"""Attach reviewed subscription evidence to the unchanged broker OAuth flow."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast, final
from urllib.parse import quote

from .execution_exhaustion import BrokerExecutionDocument, execution_failure_evidence
from .funded_transport import FundedUsageTransport
from .organization_io import SingleAttemptBrokerProviderSource
from .subscription_expiry import read_subscription_expiry

if TYPE_CHECKING:
    from .clients import JsonHttpClient, JsonHttpTransport
    from .models import AccountDescriptor, AccountObservation


class ExpiryAwareSource(SingleAttemptBrokerProviderSource):
    """Refresh quota and banked resets with the original account/tenant affinity."""

    http: JsonHttpTransport | JsonHttpClient

    @final
    def refresh_account(self, descriptor: AccountDescriptor) -> AccountObservation:
        """Read subscription evidence on every refresh, including the final recheck.

        Returns:
            The original OAuth observation enriched with reviewed date evidence.
        """
        if not isinstance(self.http, FundedUsageTransport):
            self.http = FundedUsageTransport(self.http)
        funded_http = self.http
        observation = super().refresh_account(descriptor)
        expiry = read_subscription_expiry(descriptor.label, now=observation.captured_at)
        account = self.http.request(
            method="GET",
            url=f"{self.broker_url}/v1/admin/accounts/{quote(descriptor.broker_account_id, safe='')}",
            endpoint="broker_execution_evidence",
            headers=self._broker_headers,
        )
        failure = execution_failure_evidence(
            BrokerExecutionDocument(state=cast("object", account.get("state"))),
            account_id=descriptor.broker_account_id,
        )
        return replace(
            observation,
            usage_state={
                **observation.usage_state, "funded_capacity": funded_http.capacity,
                "spendable_credits": funded_http.spendable_credits,
            },
            broker_state={**observation.broker_state, **expiry, "execution_exhaustion": failure},
        )
