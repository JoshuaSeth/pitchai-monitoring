# Copyright (c) 2026 PitchAI. All rights reserved.
"""Funded provider capability must veto quota-only reset decisions."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

from .funded_capacity import sanitize_funded_capacity
from .test_organization_execution_capacity import proved_observation
from .test_organization_reset_policy import evaluate
from .test_organization_support import NOW, SequencedSource, require_equal, run_guardian

if TYPE_CHECKING:
    from pathlib import Path

    from .funded_capacity import FundedUsageDocument
    from .models import AccountObservation


def funded_observation(payload: FundedUsageDocument, *, with_proof: bool = False) -> AccountObservation:
    """Build a full weekly window with coherent denial and independent funding.

    Returns:
        A funded account whose banked reset is a separate inventory item.
    """
    observation = proved_observation()
    return replace(
        observation,
        usage_state={
            **observation.usage_state, "allowed": False, "limit_reached": True,
            "funded_capacity": sanitize_funded_capacity(payload),
        },
        broker_state=observation.broker_state if with_proof else {},
    )


def test_funded_coherent_denial_requires_actual_execution_proof() -> None:
    """The production shape contradicts quota denial regardless of overage flags."""
    payload: FundedUsageDocument = {
        "credits": {"has_credits": True, "balance": "62206.3285900000", "unlimited": False,
                    "overage_limit_reached": False},
        "model_usage": {"gpt-6-astra": {"available": True, "credits_would_enable": False}},
        "spend_control": {"reached": False, "individual_limit": None},
    }
    require_equal(evaluate(funded_observation(payload)).state, "indeterminate")
    require_equal(evaluate(funded_observation(payload, with_proof=True)).state, "redeem")
    expired = replace(funded_observation(payload, with_proof=True), captured_at=NOW - timedelta(minutes=3))
    require_equal(evaluate(expired).state, "indeterminate")


def test_positive_unlimited_or_model_capacity_each_veto_quota_denial() -> None:
    """No spend cap, disabled overage, or contradictory flag proves credits unusable."""
    payloads: tuple[FundedUsageDocument, ...] = (
        {"credits": {"has_credits": False, "unlimited": False, "balance": "0.00001"}},
        {"credits": {"has_credits": False, "unlimited": True, "balance": "0"}},
        {"credits": {"has_credits": True, "unlimited": False, "balance": "0", "overage_limit_reached": True}},
        {"model_usage": {"gpt-6-astra": {"available": True, "credits_would_enable": False}}},
    )
    for payload in payloads:
        require_equal(evaluate(funded_observation(payload)).state, "indeterminate")


def test_plain_no_credit_and_absent_legacy_optional_fields_preserve_denial() -> None:
    """An explicit zero balance or unreported legacy extensions is not positive funding."""
    payloads: tuple[FundedUsageDocument, ...] = (
        {},
        {"credits": {"has_credits": False, "unlimited": False, "balance": "0"}},
        {"credits": {"has_credits": False, "unlimited": False, "balance": 0},
         "model_usage": {"gpt-6-astra": {"available": False, "credits_would_enable": False}},
         "spend_control": {"reached": False, "individual_limit": None}},
        {"model_usage": {"gpt-6-astra": {"available": False, "credits_would_enable": True}}},
        {"model_usage": None, "spend_control": None},
    )
    for payload in payloads:
        require_equal(evaluate(funded_observation(payload)).state, "redeem")


def test_malformed_or_incomplete_reported_funding_is_indeterminate() -> None:
    """Invalid fields cannot be coerced to false or silently discarded as legacy."""
    payloads: tuple[FundedUsageDocument, ...] = (
        {"credits": None}, {"credits": {}}, {"credits": []},
        {"credits": {"has_credits": "false", "unlimited": False, "balance": "0"}},
        {"credits": {"has_credits": False, "unlimited": 0, "balance": "0"}},
        {"credits": {"has_credits": False, "unlimited": False}},
        {"model_usage": []}, {"model_usage": {"gpt-6-astra": {}}},
        {"model_usage": {"gpt-6-astra": {"available": "false", "credits_would_enable": False}}},
        {"spend_control": {}}, {"spend_control": {"reached": "false"}},
        {"spend_control": {"reached": False, "individual_limit": "unknown"}},
    )
    for payload in payloads:
        require_equal(evaluate(funded_observation(payload)).state, "indeterminate")
        require_equal(evaluate(funded_observation(payload, with_proof=True)).state, "redeem")
    invalid_balances: tuple[object, ...] = (True, "NaN", "Infinity", "-1", [], None, "unknown")
    for balance in invalid_balances:
        invalid: FundedUsageDocument = {"credits": {"has_credits": False, "unlimited": False, "balance": balance}}
        require_equal(evaluate(funded_observation(invalid)).state, "indeterminate")


def test_funding_on_final_fleet_recheck_cancels_without_consumption(tmp_path: Path) -> None:
    """A first-pass denial cannot survive fresh funded capacity on either account."""
    initial = funded_observation({})
    funded = funded_observation({"credits": {"has_credits": True, "unlimited": False, "balance": "62500"}})
    source = SequencedSource((initial.descriptor,), {initial.descriptor.account_ref: [initial, funded]}, [])
    summary = run_guardian(tmp_path / "funding.sqlite3", source=source, now=NOW)
    require_equal(summary.redemption_count, 0)
    require_equal(len(source.consume_calls), 0)
    require_equal(evaluate(replace(funded, credits=(), available_count=0)).state, "indeterminate")


def test_current_proof_required_even_for_coherent_funded_denial() -> None:
    """Stale proof and changed quota epochs cannot use the old coherent-denial shortcut."""
    funded = funded_observation({"credits": None}, with_proof=True)
    stale = proved_observation({"occurred_at": (NOW - timedelta(seconds=121)).isoformat()})
    require_equal(evaluate(replace(funded, broker_state=stale.broker_state)).state, "indeterminate")
    require_equal(evaluate(replace(funded, broker_state={})).state, "indeterminate")
    changed_epoch = replace(funded, usage_state={**funded.usage_state, "primary_window": {
        "used_percent": 100, "limit_window_seconds": 604800,
        "reset_at": int((NOW + timedelta(days=6, seconds=1)).timestamp()),
    }})
    require_equal(evaluate(changed_epoch).state, "indeterminate")
