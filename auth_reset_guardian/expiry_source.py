# Copyright (c) 2026 PitchAI. All rights reserved.
"""Attach reviewed subscription evidence to the unchanged broker OAuth flow."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, final

from .organization_io import SingleAttemptBrokerProviderSource
from .subscription_expiry import read_subscription_expiry

if TYPE_CHECKING:
    from .models import AccountDescriptor, AccountObservation


class ExpiryAwareSource(SingleAttemptBrokerProviderSource):
    """Refresh quota and banked resets with the original account/tenant affinity."""

    @final
    def refresh_account(self, descriptor: AccountDescriptor) -> AccountObservation:
        """Read subscription evidence on every refresh, including the final recheck.

        Returns:
            The original OAuth observation enriched with reviewed date evidence.
        """
        observation = super().refresh_account(descriptor)
        expiry = read_subscription_expiry(descriptor.label, now=observation.captured_at)
        return replace(observation, broker_state={**observation.broker_state, **expiry})
