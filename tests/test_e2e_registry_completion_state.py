# Copyright (c) 2026 PitchAI. All rights reserved.
"""Regression tests for lock ownership and debounced registry health."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, NamedTuple

import pytest

from e2e_registry import db
from e2e_registry.db_schema import registry_connection
from e2e_registry.models import InvalidRegistryDataError
from e2e_registry.settings import RegistrySettings
from e2e_registry.testing import registry_lock_owner, require_test_condition

if TYPE_CHECKING:
    from pathlib import Path

_LOCK_EXPIRED_SECONDS_AGO = 30
_RECOVERY_THRESHOLD = _INVALID_HEALTH_COUNT = 2


class _StateHarness(NamedTuple):
    settings: RegistrySettings
    tenant_id: str


def _completion(status: str) -> db.RunCompletion:
    """Build a minimal completion payload.

    Returns:
        A complete runner result for the requested status.
    """
    now = time.time()
    return db.RunCompletion(
        status=status,
        elapsed_ms=10.0,
        error_kind=None,
        error_message=None,
        final_url=None,
        title=None,
        artifacts={},
        started_at_ts=now - 0.01,
        finished_at_ts=now,
    )


def _harness(root: Path) -> _StateHarness:
    settings = RegistrySettings(
        db_path=str(root / "registry.db"),
        artifacts_dir=str(root / "artifacts"),
        tests_dir=str(root / "tests"),
        runner_lock_timeout_seconds=10,
        alerts_enabled=False,
        dispatch_enabled=False,
    )
    tenant = db.create_tenant(settings, name="state-tests")
    return _StateHarness(settings=settings, tenant_id=str(tenant["id"]))


def _register(harness: _StateHarness, *, up_after_successes: int = 2) -> str:
    registration = db.NewTest(
        tenant_id=harness.tenant_id,
        name="stateful-test",
        base_url="https://autopar.pitchai.net",
        interval_seconds=3600,
        timeout_seconds=20,
        jitter_seconds=0,
        down_after_failures=1,
        up_after_successes=up_after_successes,
        notify_on_recovery=False,
        dispatch_on_failure=False,
        definition={"name": "stateful", "steps": []},
    )
    return str(db.insert_test(harness.settings, registration)["id"])


def _claim_one(harness: _StateHarness) -> db.ClaimedRun:
    claimed = db.claim_due_runs(harness.settings, max_runs=1)
    require_test_condition(
        condition=len(claimed) == 1,
        message=f"expected one claim, received {len(claimed)}",
    )
    return claimed[0]


def _trigger(harness: _StateHarness, test_id: str) -> None:
    triggered = db.trigger_run_now(
        harness.settings,
        tenant_id=harness.tenant_id,
        test_id=test_id,
    )
    require_test_condition(
        condition=triggered,
        message=f"test {test_id} was not made immediately due",
    )


def test_recovery_requires_the_configured_success_streak(tmp_path: Path) -> None:
    """A down test recovers only after its complete success debounce."""
    harness = _harness(tmp_path)
    test_id = _register(harness, up_after_successes=_RECOVERY_THRESHOLD)
    failed = db.complete_run(
        harness.settings,
        run_id=_claim_one(harness).run_id,
        completion=_completion("fail"),
    )
    require_test_condition(
        condition=failed.alerted_down,
        message="first failure did not alert down",
    )
    require_test_condition(
        condition=failed.effective_ok is False,
        message="first failure did not persist an unhealthy state",
    )

    _trigger(harness, test_id)
    first_success = db.complete_run(
        harness.settings,
        run_id=_claim_one(harness).run_id,
        completion=_completion("pass"),
    )
    require_test_condition(
        condition=not first_success.recovered_up,
        message="one success recovered before its threshold",
    )
    require_test_condition(
        condition=first_success.effective_ok is False,
        message="one success marked the test healthy",
    )
    require_test_condition(
        condition=first_success.success_streak == 1,
        message="first recovery success did not increment its streak",
    )

    _trigger(harness, test_id)
    recovery = db.complete_run(
        harness.settings,
        run_id=_claim_one(harness).run_id,
        completion=_completion("pass"),
    )
    require_test_condition(
        condition=recovery.recovered_up,
        message="second success did not report recovery",
    )
    require_test_condition(
        condition=recovery.effective_ok is True,
        message="second success did not persist a healthy state",
    )
    require_test_condition(
        condition=recovery.success_streak == _RECOVERY_THRESHOLD,
        message="recovery streak did not reach two",
    )


def test_duplicate_completion_is_rejected_without_state_mutation(
    tmp_path: Path,
) -> None:
    """A finished run cannot be replayed to overwrite health state."""
    harness = _harness(tmp_path)
    test_id = _register(harness, up_after_successes=1)
    run_id = _claim_one(harness).run_id
    accepted = db.complete_run(
        harness.settings,
        run_id=run_id,
        completion=_completion("fail"),
    )
    duplicate = db.complete_run(
        harness.settings,
        run_id=run_id,
        completion=_completion("pass"),
    )
    test = db.get_test(harness.settings, tenant_id=harness.tenant_id, test_id=test_id)
    require_test_condition(condition=accepted.updated, message="first completion was not accepted")
    require_test_condition(condition=not duplicate.updated, message="duplicate completion was accepted")
    require_test_condition(condition=test is not None, message="completed test disappeared")
    require_test_condition(
        condition=test is not None and test["effective_ok"] == 0,
        message="duplicate changed effective health",
    )
    require_test_condition(
        condition=test is not None and test["fail_streak"] == 1,
        message="duplicate changed the failure streak",
    )


def test_stale_completion_cannot_clear_a_newer_lock(tmp_path: Path) -> None:
    """An expired run cannot complete after another runner reclaims its test."""
    harness = _harness(tmp_path)
    test_id = _register(harness, up_after_successes=1)
    stale_run = _claim_one(harness)
    with registry_connection(harness.settings) as connection:
        connection.execute(
            "UPDATE test_state SET running_locked_at_ts=? WHERE test_id=?",
            (time.time() - _LOCK_EXPIRED_SECONDS_AGO, test_id),
        )
    current_run = _claim_one(harness)
    stale = db.complete_run(
        harness.settings,
        run_id=stale_run.run_id,
        completion=_completion("fail"),
    )
    require_test_condition(condition=not stale.updated, message="stale completion was accepted")
    require_test_condition(
        condition=registry_lock_owner(harness.settings, test_id) == current_run.run_id,
        message="stale completion cleared the current lock",
    )
    accepted = db.complete_run(
        harness.settings,
        run_id=current_run.run_id,
        completion=_completion("pass"),
    )
    require_test_condition(condition=accepted.updated, message="current lock owner could not complete")


def test_missing_and_corrupt_health_are_fail_closed(tmp_path: Path) -> None:
    """Status summaries never coerce absent or corrupt state to healthy."""
    harness = _harness(tmp_path)
    first_test_id = _register(harness)
    second_test_id = _register(harness)
    with registry_connection(harness.settings) as connection:
        connection.execute("DELETE FROM test_state WHERE test_id=?", (first_test_id,))
        connection.execute(
            "UPDATE test_state SET effective_ok=2 WHERE test_id=?",
            (second_test_id,),
        )
    summary = db.status_summary(harness.settings)
    require_test_condition(
        condition=summary["failing_tests"] == _INVALID_HEALTH_COUNT,
        message="invalid health was not counted as failing",
    )


def test_corrupt_health_prevents_completion_and_preserves_lock(tmp_path: Path) -> None:
    """Completion fails loudly before mutating an invalid persisted state."""
    harness = _harness(tmp_path)
    test_id = _register(harness)
    run_id = _claim_one(harness).run_id
    with registry_connection(harness.settings) as connection:
        connection.execute(
            "UPDATE test_state SET effective_ok=2 WHERE test_id=?",
            (test_id,),
        )
    with pytest.raises(InvalidRegistryDataError):
        db.complete_run(harness.settings, run_id=run_id, completion=_completion("pass"))
    require_test_condition(
        condition=registry_lock_owner(harness.settings, test_id) == run_id,
        message="invalid completion changed lock ownership",
    )
