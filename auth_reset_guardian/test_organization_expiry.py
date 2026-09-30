# Copyright (c) 2026 PitchAI. All rights reserved.
"""Expiry ordering and subscription evidence regression proofs."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

from .subscription_expiry import SubscriptionDocument, subscription_expiry
from .test_organization_reset_policy import evaluate
from .test_organization_support import NOW, account_observation, require_equal, reset_credit

if TYPE_CHECKING:
    from .models import AccountObservation


def with_end(observation: AccountObservation, end: str) -> AccountObservation:
    """Attach confirmed subscription evidence, preserving separate reset expiry.

    Returns:
        An observation carrying the separately reviewed access-end date.
    """
    return replace(observation, broker_state={
        **observation.broker_state,
        "subscription_access_ends_on": end,
        "subscription_timezone": "Europe/Berlin",
    })


def selected_label(*observations: AccountObservation) -> str | None:
    """Return the selected account label for a policy fixture."""
    selected = evaluate(*observations).selection
    return selected.observation.descriptor.label if selected else None


def test_confirmed_subscription_end_precedes_credit_and_weekly_ordering() -> None:
    """Prioritize soonest subscription end, even with a later reset-credit expiry."""
    early_credit = reset_credit("early-credit", expires_at=NOW + timedelta(days=1))
    late_credit = reset_credit("late-credit", expires_at=NOW + timedelta(days=20))
    soon = with_end(account_observation("soon@example.test", credit_bank=(late_credit,)), "2026-09-08")
    later = with_end(account_observation("later@example.test", credit_bank=(early_credit,)), "2026-09-10")
    unknown = account_observation("unknown@example.test", credit_bank=(early_credit,))
    require_equal(selected_label(unknown, later, soon), soon.descriptor.label)
    require_equal(selected_label(soon, later, unknown), soon.descriptor.label)


def test_equal_subscription_dates_use_earliest_credit_across_and_within_accounts() -> None:
    """Account and provider array order do not choose the consumed credit."""
    early = reset_credit("early", expires_at=NOW + timedelta(hours=1))
    late = reset_credit("late", expires_at=NOW + timedelta(days=20))
    first = with_end(account_observation("first@example.test", credit_bank=(late,)), "2026-09-10")
    second = with_end(account_observation("second@example.test", credit_bank=(late, early)), "2026-09-10")
    selection = evaluate(first, second).selection
    require_equal(selection.credit.credit_ref if selection else None, early.credit_ref)
    require_equal(selected_label(first, second), second.descriptor.label)


def test_expiry_never_overrides_partial_capacity_or_missing_resets() -> None:
    """No subscription deadline authorizes artificial usage or an empty-bank reset."""
    credit = reset_credit("urgent", expires_at=NOW + timedelta(hours=1))
    urgent = with_end(account_observation("urgent@example.test", credit_bank=(credit,)), "2026-09-08")
    partial = account_observation("partial@example.test", used_percent=99)
    require_equal(evaluate(urgent, partial).state, "not_exhausted")
    empty = replace(urgent, credits=(), available_count=0)
    require_equal(evaluate(empty).state, "no_eligible_credit")
    ended = with_end(urgent, "2026-09-07")
    require_equal(evaluate(ended).state, "no_eligible_credit")


def test_subscription_change_changes_final_recheck_identity() -> None:
    """A changed reviewed end date invalidates the initial consume decision."""
    credit = reset_credit("credit", expires_at=NOW + timedelta(days=10))
    initial = with_end(account_observation("account@example.test", credit_bank=(credit,)), "2026-09-10")
    changed = with_end(initial, "2026-09-11")
    require_equal(evaluate(initial).decision_key == evaluate(changed).decision_key, expected=False)


def test_subscription_parser_does_not_infer_expiry_from_other_credit_dates() -> None:
    """Renewals, assigned credits, and quota resets are not subscription endings."""
    row: dict[str, object] = {
        "email": "account@example.test", "access_status": "active",
        "renewal_enabled": False, "access_ends_on": "2026-09-10",
        "verified_at": NOW.isoformat(), "verified_source": "signed-in billing review",
    }
    document = SubscriptionDocument(schema_version=1, timezone="Europe/Berlin", accounts=[row])
    confirmed = subscription_expiry(document, label="account@example.test", now=NOW)
    require_equal(confirmed["subscription_access_ends_on"], "2026-09-10")
    for change in (
        {"renewal_enabled": True},
        {"verified_at": (NOW - timedelta(days=31)).isoformat()},
        {"verified_at": (NOW + timedelta(days=1)).isoformat()},
        {"verified_source": None},
        {"access_ends_on": None, "renews_on": "2026-09-10", "assigned_credit_expires_at": "2026-09-10"},
    ):
        changed: SubscriptionDocument = {**document, "accounts": [{**row, **change}]}
        result = subscription_expiry(changed, label="account@example.test", now=NOW)
        require_equal(result["subscription_access_ends_on"], None)
