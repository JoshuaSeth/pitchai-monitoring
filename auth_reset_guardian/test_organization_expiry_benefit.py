# Copyright (c) 2026 PitchAI. All rights reserved.
"""Expiry urgency never waives actual exhaustion or exact subscription evidence."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

from .models import PayloadError
from .subscription_expiry import SubscriptionDocument, subscription_expiry
from .test_organization_expiry import with_end
from .test_organization_reset_policy import evaluate
from .test_organization_support import NOW, account_observation, contradictory_observation, require_equal, reset_credit

if TYPE_CHECKING:
    from .models import AccountObservation


def test_expiry_exception_requires_actual_exhaustion() -> None:
    """An urgent credit permits a short reset distance, never a capacity bypass."""
    credit = reset_credit("urgent", expires_at=NOW + timedelta(hours=1))
    full = account_observation("full@example.test", weekly_reset_at=NOW + timedelta(hours=24), credit_bank=(credit,))
    unknown = contradictory_observation("unknown@example.test", credit_bank=(credit,))
    partial = account_observation("partial@example.test", used_percent=99)
    require_equal(evaluate(full).state, "redeem")
    require_equal(evaluate(full, unknown).state, "indeterminate")
    require_equal(evaluate(full, partial).state, "not_exhausted")
    require_equal(evaluate(replace(full, credits=(), available_count=0)).state, "no_eligible_credit")


def test_exact_entitlement_end_allows_use_after_cancel_before_natural_reset() -> None:
    """Cancellation time is distinct from the reviewed access cutoff."""
    credit = reset_credit("banked", expires_at=NOW + timedelta(days=30))
    observation = with_end(
        account_observation("ending@example.test", weekly_reset_at=NOW + timedelta(hours=49), credit_bank=(credit,)),
        NOW.date().isoformat(),
    )
    exact = replace(observation, broker_state={
        **observation.broker_state,
        "subscription_access_ends_at": (NOW + timedelta(hours=6)).isoformat(),
        "provider_cancels_at": (NOW - timedelta(hours=1)).isoformat(),
    })
    require_equal(evaluate(exact).state, "redeem")
    expired = replace(exact, broker_state={**exact.broker_state, "subscription_access_ends_at": NOW.isoformat()})
    require_equal(evaluate(expired).state, "no_eligible_credit")
    changed = replace(exact, broker_state={
        **exact.broker_state, "subscription_access_ends_at": (NOW + timedelta(hours=7)).isoformat(),
    })
    require_equal(evaluate(exact).decision_key == evaluate(changed).decision_key, expected=False)


def test_date_only_under_four_days_still_waits_for_nearby_natural_reset() -> None:
    """Subscription urgency alone never waives the strict weekly-distance gate."""
    credit = reset_credit("banked", expires_at=NOW + timedelta(days=30))
    early_reset = with_end(
        account_observation("ending@example.test", weekly_reset_at=NOW + timedelta(hours=24), credit_bank=(credit,)),
        "2026-09-08",
    )
    late_reset = with_end(
        account_observation("ending@example.test", weekly_reset_at=NOW + timedelta(hours=40), credit_bank=(credit,)),
        "2026-09-08",
    )
    require_equal(evaluate(early_reset).state, "no_eligible_credit")
    require_equal(evaluate(late_reset).state, "no_eligible_credit")


def test_exact_cutoff_parser_rejects_conflicts_and_ignores_other_expiries() -> None:
    """Only reviewed entitlement end fields can supply the precise access cutoff."""
    row: dict[str, object] = {
        "email": "account@example.test", "access_status": "active", "renewal_enabled": False,
        "access_ends_on": "2026-09-08", "access_ends_at": "2026-09-08T18:50:54Z",
        "verified_at": NOW.isoformat(), "verified_source": "provider entitlement",
        "provider_cancels_at": "2026-09-08T12:50:54Z", "assigned_credit_expires_at": "2026-12-31T00:00:00Z",
    }
    document = SubscriptionDocument(schema_version=1, timezone="Europe/Berlin", accounts=[row])
    result = subscription_expiry(document, label="account@example.test", now=NOW)
    require_equal(result["subscription_access_ends_at"], "2026-09-08T18:50:54.000000Z")
    for invalid in ("2026-09-09T18:50:54Z", "2026-09-08T18:50:54"):
        changed: SubscriptionDocument = {**document, "accounts": [{**row, "access_ends_at": invalid}]}
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(subscription_expiry, changed, label="account@example.test", now=NOW)
        require_equal(isinstance(future.exception(), PayloadError), expected=True)


def test_exact_cutoffs_sort_before_credit_expiry_on_same_day() -> None:
    """Choose the subscription with earlier verified access loss on an equal date."""
    early_credit = reset_credit("early-credit", expires_at=NOW + timedelta(hours=1))
    late_credit = reset_credit("late-credit", expires_at=NOW + timedelta(days=30))
    observations: list[AccountObservation] = []
    for hours, credit in ((8, early_credit), (6, late_credit)):
        observation = with_end(account_observation(str(hours), credit_bank=(credit,)), NOW.date().isoformat())
        observations.append(replace(observation, broker_state={
            **observation.broker_state, "subscription_access_ends_at": (NOW + timedelta(hours=hours)).isoformat(),
        }))
    selection = evaluate(*observations).selection
    require_equal(selection.credit.credit_ref if selection else None, late_credit.credit_ref)


def test_expiry_exception_does_not_authorize_reset_after_natural_reset() -> None:
    """A stale exhausted window cannot justify spending even an urgent credit."""
    credit = reset_credit("urgent", expires_at=NOW + timedelta(hours=1))
    for distance in (timedelta(0), timedelta(seconds=-1)):
        observation = account_observation("account", weekly_reset_at=NOW + distance, credit_bank=(credit,))
        require_equal(evaluate(observation).state, "indeterminate")
