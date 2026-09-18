# Copyright (c) 2026 PitchAI. All rights reserved.
"""Pure policy proofs for organization-wide reset redemption."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

from .organization_policy import evaluate_organization
from .test_organization_support import (
    NOW,
    account_observation,
    contradictory_observation,
    disabled_observation,
    require,
    require_equal,
    reset_credit,
)

if TYPE_CHECKING:
    from .models import AccountObservation
    from .organization_policy import OrganizationDecision


def evaluate(*observations: AccountObservation) -> OrganizationDecision:
    """Evaluate typed observations without duplicating broker mappings.

    Returns:
        The complete organization policy decision.
    """
    descriptors = [item.descriptor for item in observations]
    mapping = {item.descriptor.account_ref: item for item in observations}
    return evaluate_organization(
        descriptors=descriptors,
        observations=mapping,
        failed_account_refs=set(),
        now=NOW,
    )


def test_furthest_weekly_reset_wins_across_exhausted_accounts() -> None:
    """Choose one account by natural weekly distance, never by expiry alone."""
    near_credit = reset_credit("support-reset", expires_at=NOW + timedelta(days=20))
    far_credit = reset_credit("elise-reset", expires_at=NOW + timedelta(days=10))
    support = account_observation(
        "support@pitchai.net",
        weekly_reset_at=NOW + timedelta(days=3),
        credit_bank=(near_credit,),
    )
    elise = account_observation(
        "elise@pitchai.net",
        weekly_reset_at=NOW + timedelta(days=7),
        credit_bank=(far_credit,),
    )

    decision = evaluate(support, elise)

    require_equal(decision.state, "redeem")
    selection = decision.selection
    require(
        condition=selection is not None,
        message="redeem decision omitted its selection",
    )
    if selection is None:
        return
    require_equal(selection.observation.descriptor.label, "elise@pitchai.net")
    require_equal(selection.credit.credit_ref, far_credit.credit_ref)


def test_exactly_48_hours_is_ineligible_but_one_second_more_is_eligible() -> None:
    """Enforce Seth's strict boundary independent of the credit expiry horizon."""
    credit = reset_credit("boundary-reset", expires_at=NOW + timedelta(days=30))
    exact = account_observation(
        "exact@pitchai.net",
        weekly_reset_at=NOW + timedelta(hours=48),
        credit_bank=(credit,),
    )
    beyond = account_observation(
        "beyond@pitchai.net",
        weekly_reset_at=NOW + timedelta(hours=48, seconds=1),
        credit_bank=(credit,),
    )

    require_equal(evaluate(exact).state, "no_eligible_credit")
    require_equal(evaluate(beyond).state, "redeem")


def test_positive_or_zero_used_capacity_prevents_organization_exhaustion() -> None:
    """Treat zero used as full remaining capacity, not exhaustion."""
    credit = reset_credit("unused-reset", expires_at=NOW + timedelta(days=10))
    exhausted = account_observation("spent@pitchai.net", credit_bank=(credit,))
    partly_used = account_observation("partial@pitchai.net", used_percent=99)
    unused = account_observation("unused@pitchai.net", used_percent=0)

    require_equal(evaluate(exhausted, partly_used).state, "not_exhausted")
    require_equal(evaluate(exhausted, unused).state, "not_exhausted")


def test_stale_failed_and_contradictory_evidence_fail_closed() -> None:
    """Reject every incomplete or incoherent organization-wide proof."""
    credit = reset_credit("safe-reset", expires_at=NOW + timedelta(days=10))
    stale = account_observation(
        "stale@pitchai.net",
        captured_at=NOW - timedelta(minutes=3),
        weekly_reset_at=NOW + timedelta(days=7),
        credit_bank=(credit,),
    )
    contradictory = contradictory_observation(
        "schedule@pitchai.net",
        credit_bank=(credit,),
    )
    fresh = account_observation("failed@pitchai.net", credit_bank=(credit,))
    failed = evaluate_organization(
        descriptors=[fresh.descriptor],
        observations={fresh.descriptor.account_ref: fresh},
        failed_account_refs={fresh.descriptor.account_ref},
        now=NOW,
    )

    require_equal(evaluate(stale).state, "indeterminate")
    require_equal(evaluate(contradictory).state, "indeterminate")
    require_equal(failed.state, "indeterminate")


def test_disabled_accounts_are_excluded_but_never_form_empty_proof() -> None:
    """Preserve lifecycle exclusions without declaring an empty fleet exhausted."""
    credit = reset_credit("enabled-reset", expires_at=NOW + timedelta(days=10))
    disabled = disabled_observation("disabled@pitchai.net", credit_bank=(credit,))
    exhausted = account_observation("enabled@pitchai.net", credit_bank=(credit,))

    require_equal(evaluate(disabled).state, "indeterminate")
    require_equal(evaluate(disabled, exhausted).state, "redeem")


def test_zero_authoritative_available_count_blocks_a_listed_credit() -> None:
    """Do not treat a contradictory listed detail as an actually available bank."""
    credit = reset_credit("count-mismatch-reset", expires_at=NOW + timedelta(days=10))
    listed = account_observation("elise@pitchai.net", credit_bank=(credit,))
    unavailable = replace(listed, available_count=0)

    require_equal(evaluate(unavailable).state, "no_eligible_credit")


def test_two_distinct_weekly_window_resets_are_ineligible() -> None:
    """Fail closed when provider windows do not identify one natural weekly reset."""
    credit = reset_credit("ambiguous-weekly-reset", expires_at=NOW + timedelta(days=10))
    observation = account_observation("elise@pitchai.net", credit_bank=(credit,))
    later_reset = NOW + timedelta(days=7, hours=1)
    usage_state = {
        **observation.usage_state,
        "secondary_window": {
            "limit_window_seconds": 604800,
            "reset_at": int(later_reset.timestamp()),
            "used_percent": 100,
        },
    }
    ambiguous = replace(observation, usage_state=usage_state)

    require_equal(evaluate(ambiguous).state, "no_eligible_credit")
