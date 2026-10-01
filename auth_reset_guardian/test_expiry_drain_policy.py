# Copyright (c) 2026 PitchAI. All rights reserved.
"""Expiry-first replenishment, automatic-reset boundaries, and fresh rechecks."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from .models import ConsumeResult
from .test_organization_expiry import with_end
from .test_organization_reset_policy import evaluate
from .test_organization_support import (
    NOW,
    SequencedSource,
    account_observation,
    require_equal,
    reset_credit,
    run_guardian,
)

if TYPE_CHECKING:
    from pathlib import Path

    from .models import AccountObservation


def ending_account(
    label: str, *, expiry_hours: int, reset_hours: int = 24, used: int = 100,
) -> AccountObservation:
    """Create exact-cutoff evidence with one banked reset and no funded ambiguity.

    Returns:
        A provider observation with verified subscription expiry.
    """
    end = NOW + timedelta(hours=expiry_hours)
    credit = reset_credit(label + "-reset", expires_at=NOW + timedelta(days=30))
    observation = with_end(
        account_observation(
            label,
            used_percent=used,
            weekly_reset_at=NOW + timedelta(hours=reset_hours),
            credit_bank=(credit,),
        ),
        end.date().isoformat(),
    )
    return replace(
        observation,
        broker_state={
            **observation.broker_state,
            "subscription_access_ends_at": end.isoformat(),
        },
    )


@pytest.mark.parametrize(
    ("expiry_hours", "reset_hours", "expected"),
    [
        (96, 48, "no_eligible_credit"),
        (97, 24, "no_eligible_credit"),
        (96, 49, "redeem"),
        (95, 24, "redeem"),
        (72, 48, "redeem"),
        (24, 48, "redeem"),
        (0, 48, "no_eligible_credit"),
    ],
)
def test_four_day_two_day_boundaries(
    expiry_hours: int, reset_hours: int, expected: str,
) -> None:
    """Both thresholds are inclusive and confirmed expiry never gets extended."""
    require_equal(
        evaluate(
            ending_account("target", expiry_hours=expiry_hours, reset_hours=reset_hours),
        ).state,
        expected,
    )


def test_use_target_allowance_and_credits_before_spending_its_bank() -> None:
    """Existing capacity on the current drain account suppresses redemption."""
    target = ending_account("first", expiry_hours=72, used=99)
    later = ending_account("later", expiry_hours=120, reset_hours=72)
    require_equal(evaluate(later, target).state, "not_exhausted")
    funded = ending_account("first", expiry_hours=72)
    funded = replace(
        funded, usage_state={**funded.usage_state, "spendable_credits": True},
    )
    require_equal(evaluate(later, funded).state, "not_exhausted")


def test_near_weekly_reset_parks_target_and_allows_next_expiry() -> None:
    """An exhausted account with four days left waits while the next is replenished."""
    waiting = ending_account("first", expiry_hours=96, reset_hours=24)
    later = ending_account("later", expiry_hours=144, reset_hours=72)
    selected = evaluate(later, waiting).selection
    require_equal(selected.observation.descriptor.label if selected else None, "later")


def test_bank_expiring_before_weekly_reset_is_not_left_to_expire() -> None:
    """A credit's own earlier expiry overrides waiting for the weekly reset."""
    waiting = ending_account("target", expiry_hours=120, reset_hours=24)
    urgent = reset_credit("urgent", expires_at=NOW + timedelta(hours=12))
    require_equal(evaluate(replace(waiting, credits=(urgent,))).state, "redeem")


def test_expiry_drain_redeems_exactly_once_with_later_account_available(
    tmp_path: Path,
) -> None:
    """The full durable workflow restores the target while later capacity exists."""
    first = ending_account("first", expiry_hours=72)
    later = ending_account("later", expiry_hours=144, used=0)
    restored = replace(
        ending_account("first", expiry_hours=72, reset_hours=168, used=0),
        credits=(),
        available_count=0,
    )
    source = SequencedSource(
        (first.descriptor, later.descriptor),
        {
            first.descriptor.account_ref: [first, first, restored, restored],
            later.descriptor.account_ref: [later],
        },
        [ConsumeResult(code="reset", windows_reset=1)],
    )
    summary = run_guardian(tmp_path / "audit.sqlite3", source=source, now=NOW)
    require_equal(summary.status, "ok")
    require_equal(summary.redemption_count, 1)
    require_equal(len(source.consume_calls), 1)
    require_equal(source.consume_calls[0][0], first.descriptor.account_ref)


def test_target_recovery_at_final_recheck_prevents_redemption(tmp_path: Path) -> None:
    """Newly available credits or quota cancel a claimed reset before consume."""
    first = ending_account("first", expiry_hours=72)
    recovered = replace(
        first, usage_state={**first.usage_state, "spendable_credits": True},
    )
    later = ending_account("later", expiry_hours=144, used=0)
    source = SequencedSource(
        (first.descriptor, later.descriptor),
        {
            first.descriptor.account_ref: [first, recovered],
            later.descriptor.account_ref: [later],
        },
        [],
    )
    summary = run_guardian(tmp_path / "audit.sqlite3", source=source, now=NOW)
    require_equal(summary.redemption_count, 0)
    require_equal(len(source.consume_calls), 0)


def test_stale_inventory_prevents_expiry_redemption() -> None:
    """A stale later account cannot silently hide an earlier expiry."""
    target = ending_account("first", expiry_hours=72)
    stale = replace(
        ending_account("later", expiry_hours=120),
        captured_at=NOW - timedelta(minutes=3),
    )
    require_equal(evaluate(target, stale).state, "indeterminate")
