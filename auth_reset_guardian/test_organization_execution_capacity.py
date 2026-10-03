# Copyright (c) 2026 PitchAI. All rights reserved.
"""Actual execution proof must survive full-fleet freshness and the final recheck."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

from .execution_exhaustion import execution_failure_evidence
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

    from .execution_exhaustion import BrokerExecutionReport
    from .models import AccountObservation


def provider_proof() -> BrokerExecutionReport:
    """Return broker v1 evidence from an actual current-epoch execution error."""
    return {
        "schema_version": 1, "source": "provider_execution_error", "error_code": "usage_limit_reached",
        "occurred_at": (NOW - timedelta(seconds=30)).isoformat(),
        "received_at": (NOW - timedelta(seconds=20)).isoformat(),
        "account_id": "broker:account", "lease_id": "private-lease", "client_name": "private-client",
        "quota_windows": {"primary_window": {
            "limit_window_seconds": 604800, "reset_at": int((NOW + timedelta(days=6)).timestamp()),
        }},
    }


def proved_observation(change: BrokerExecutionReport | None = None) -> AccountObservation:
    """Build a permissive-flag observation carrying sanitized provider execution proof.

    Returns:
        A fresh exhausted included window whose effective exhaustion needs the proof.
    """
    credit = reset_credit("banked", expires_at=NOW + timedelta(hours=1))
    observation = account_observation("account", weekly_reset_at=NOW + timedelta(days=6), credit_bank=(credit,))
    proof = {**provider_proof(), **(change or {})}
    sanitized = execution_failure_evidence({"state": {"execution_exhaustion": proof}}, account_id="broker:account")
    return replace(observation, usage_state={**observation.usage_state, "allowed": True, "limit_reached": False},
                   broker_state={"execution_exhaustion": sanitized})


def test_fresh_execution_error_establishes_effective_exhaustion_without_leaking_identity() -> None:
    """A current actual error resolves permissive flags without manufacturing traffic."""
    observation = proved_observation()
    require_equal(evaluate(observation).state, "redeem")
    serialized = json.dumps(observation.broker_state)
    for private in ("broker:account", "private-lease", "private-client"):
        require_equal(private in serialized, expected=False)


def test_stale_future_delayed_or_unbound_failures_do_not_qualify() -> None:
    """The server receipt cannot freshen an old execution or a different quota epoch."""
    changes: tuple[BrokerExecutionReport, ...] = (
        {"occurred_at": (NOW - timedelta(seconds=121)).isoformat()},
        {"received_at": (NOW + timedelta(seconds=1)).isoformat()},
        {"occurred_at": (NOW + timedelta(seconds=1)).isoformat()},
        {"received_at": (NOW - timedelta(seconds=40)).isoformat()},
        {"quota_windows": {}}, {"quota_windows": {"primary_window": None}},
        {"quota_windows": {"primary_window": {"limit_window_seconds": True, "reset_at": 5}}},
    )
    for change in changes:
        require_equal(evaluate(proved_observation(change)).state, "indeterminate")
    observation = proved_observation()
    before_receipt = replace(observation, captured_at=NOW - timedelta(seconds=25))
    require_equal(evaluate(before_receipt).state, "indeterminate")


def test_positive_capacity_or_a_changed_epoch_invalidates_execution_proof() -> None:
    """A reset after the error invalidates proof even if a current window reads full."""
    observation = proved_observation()
    positive = account_observation("account", used_percent=99, credit_bank=observation.credits)
    require_equal(evaluate(replace(positive, broker_state=observation.broker_state)).state, "not_exhausted")
    changed = account_observation("account", weekly_reset_at=NOW + timedelta(days=6, seconds=1))
    stale_epoch = replace(observation, usage_state={**changed.usage_state, "allowed": True, "limit_reached": False})
    require_equal(evaluate(stale_epoch).state, "indeterminate")
    partial = account_observation("partial", used_percent=0)
    require_equal(evaluate(observation, partial).state, "not_exhausted")


def test_loss_of_execution_proof_on_final_recheck_cancels_without_consuming(tmp_path: Path) -> None:
    """Success-cleared or missing proof cannot survive the complete second refresh."""
    initial = proved_observation()
    cleared = replace(initial, broker_state={"execution_exhaustion": None})
    source = SequencedSource((initial.descriptor,), {initial.descriptor.account_ref: [initial, cleared]}, [])
    summary = run_guardian(tmp_path / "proof.sqlite3", source=source, now=NOW)
    require_equal(summary.redemption_count, 0)
    require_equal(len(source.consume_calls), 0)


def test_confirmed_spendable_credits_override_earlier_execution_denial() -> None:
    """Current credit permission prevents a reset despite a retained fresh denial."""
    initial = proved_observation()
    recovered = replace(initial, usage_state={**initial.usage_state, "spendable_credits": True})
    require_equal(evaluate(recovered).state, "not_exhausted")


def test_credit_recovery_on_final_recheck_cancels_with_proof_retained(tmp_path: Path) -> None:
    """Recovery of usable credits cancels consumption even before proof is cleared."""
    initial = proved_observation()
    recovered = replace(initial, usage_state={**initial.usage_state, "spendable_credits": True})
    source = SequencedSource((initial.descriptor,), {initial.descriptor.account_ref: [initial, recovered]}, [])
    summary = run_guardian(tmp_path / "credit-recovery.sqlite3", source=source, now=NOW)
    require_equal(summary.redemption_count, 0)
    require_equal(len(source.consume_calls), 0)


def test_reported_malformed_secondary_epoch_cannot_be_silently_omitted() -> None:
    """Every reported non-null current window needs a complete matching epoch."""
    observation = proved_observation()
    invalid_windows: tuple[object, ...] = ({}, {"limit_window_seconds": 18000}, {"reset_at": True}, "invalid")
    for secondary in invalid_windows:
        malformed = replace(observation, usage_state={**observation.usage_state, "secondary_window": secondary})
        require_equal(evaluate(malformed).state, "indeterminate")
    absent = replace(observation, usage_state={**observation.usage_state, "secondary_window": None})
    require_equal(evaluate(absent).state, "redeem")
