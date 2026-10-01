# Copyright (c) 2026 PitchAI. All rights reserved.
"""Expiry-first draining and the four-day / two-day banked-reset exception."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from .subscription_expiry import (
    confirmed_end_date,
    confirmed_end_time,
    subscription_end_upper_bound,
    subscription_may_have_ended,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from .models import AccountObservation, ResetCredit

MINIMUM_EXPIRY_DISTANCE = timedelta(days=4)
NATURAL_RESET_WAIT = timedelta(days=2)


def expiry_drain_accounts(
    observations: Mapping[str, AccountObservation],
    *,
    now: datetime,
) -> tuple[AccountObservation, ...]:
    """Return enabled, confirmed expiring accounts in cancellation order."""
    candidates = [
        observation
        for observation in observations.values()
        if observation.descriptor.enabled
        and confirmed_end_date(observation) is not None
        and not subscription_may_have_ended(observation, now=now)
    ]
    return tuple(sorted(candidates, key=_drain_rank))


def _drain_rank(observation: AccountObservation) -> tuple[str, float, float, str]:
    exact = confirmed_end_time(observation)
    credit_expiries = [
        credit.expires_at.timestamp()
        for credit in observation.credits
        if credit.is_redeemable and credit.expires_at is not None
    ]
    return (
        confirmed_end_date(observation) or "9999-12-31",
        exact.timestamp() if exact is not None else float("inf"),
        min(credit_expiries, default=float("inf")),
        observation.descriptor.account_ref,
    )


def should_preserve_reset(
    observation: AccountObservation,
    credit: ResetCredit,
    *,
    weekly_reset_at: datetime,
    now: datetime,
) -> bool:
    """Require confirmed expiry within four days and a weekly reset beyond two.

    Date-only evidence uses the whole end-day upper bound for this comparison.
    A reset credit expiring before the natural reset must not be left to expire.

    Returns:
        Whether this exhausted account should wait instead of consuming its bank.
    """
    if credit.expires_at is not None and credit.expires_at <= weekly_reset_at:
        return False
    latest_end = subscription_end_upper_bound(observation)
    if latest_end is None:
        # Unknown dates can only reach the separate whole-fleet exhaustion fallback.
        return weekly_reset_at - now <= NATURAL_RESET_WAIT
    return (
        latest_end - now >= MINIMUM_EXPIRY_DISTANCE
        or weekly_reset_at - now <= NATURAL_RESET_WAIT
    )
