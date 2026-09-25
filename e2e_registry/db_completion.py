# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock-safe persistence for completed E2E runs."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from e2e_registry.db_core import fetch_one_row, row_record, utc_timestamp
from e2e_registry.db_health import (
    HealthTransition,
    completion_context,
    persist_observed_state,
)
from e2e_registry.db_schema import registry_connection
from e2e_registry.models import CompletionOutcome, dump_json

if TYPE_CHECKING:
    import sqlite3

    from e2e_registry.db_health import (
        CompletionContext,
    )
    from e2e_registry.models import RunCompletion
    from e2e_registry.settings import RegistrySettings

_ALLOWED_COMPLETION_STATUSES = frozenset({"pass", "fail", "infra_degraded"})


class LostRunLockError(RuntimeError):
    """Raised when a run loses ownership during an atomic completion."""


def _empty_outcome(run_id: str | None) -> CompletionOutcome:
    return CompletionOutcome(
        updated=False,
        alerted_down=False,
        recovered_up=False,
        effective_ok=None,
        fail_streak=None,
        success_streak=None,
        tenant_id=None,
        test_id=None,
        test_name=None,
        run_id=run_id,
    )


def _persist_completion(
    connection: sqlite3.Connection,
    run_id: str,
    completion: RunCompletion,
) -> None:
    result = connection.execute(
        """
        UPDATE runs
        SET started_at_ts=?, finished_at_ts=?, status=?, elapsed_ms=?, error_kind=?, error_message=?,
            final_url=?, title=?, artifacts_json=?
        WHERE id=? AND finished_at_ts IS NULL
        """,
        (
            completion.started_at_ts,
            completion.finished_at_ts,
            completion.status,
            completion.elapsed_ms,
            completion.error_kind,
            completion.error_message,
            completion.final_url,
            completion.title,
            dump_json(completion.artifacts),
            run_id,
        ),
    )
    if result.rowcount != 1:
        message = f"Run {run_id} was already completed"
        raise LostRunLockError(message)


def _infra_transition(context: CompletionContext) -> HealthTransition:
    return HealthTransition(
        effective_ok=context.effective_ok,
        fail_streak=context.fail_streak,
        success_streak=context.success_streak,
        alerted_down=False,
        recovered_up=False,
    )


def _complete_owned_run(
    connection: sqlite3.Connection,
    run_id: str,
    completion: RunCompletion,
    context: CompletionContext,
    *,
    now: float,
) -> CompletionOutcome:
    _persist_completion(connection, run_id, completion)
    jitter = secrets.randbelow(context.jitter_seconds + 1) if context.jitter_seconds else 0
    next_due = now + context.interval_seconds + jitter
    lock_result = connection.execute(
        """
        UPDATE test_state
        SET running_lock_id=NULL, running_locked_at_ts=NULL, next_due_ts=?
        WHERE test_id=? AND running_lock_id=?
        """,
        (next_due, context.test_id, run_id),
    )
    if lock_result.rowcount != 1:
        message = f"Run {run_id} no longer owns the test lock"
        raise LostRunLockError(message)
    if completion.status == "infra_degraded":
        connection.execute(
            "UPDATE test_state SET last_infra_ts=? WHERE test_id=?",
            (now, context.test_id),
        )
        transition = _infra_transition(context)
    else:
        transition = persist_observed_state(
            connection,
            context,
            observed_ok=completion.status == "pass",
            now=now,
        )
    return CompletionOutcome(
        updated=True,
        alerted_down=transition.alerted_down,
        recovered_up=transition.recovered_up,
        effective_ok=transition.effective_ok,
        fail_streak=transition.fail_streak,
        success_streak=transition.success_streak,
        tenant_id=context.tenant_id,
        test_id=context.test_id,
        test_name=context.test_name,
        run_id=run_id,
    )


def _complete_transaction(
    connection: sqlite3.Connection,
    run_id: str,
    completion: RunCompletion,
) -> CompletionOutcome:
    with connection:
        connection.execute("BEGIN IMMEDIATE;")
        row = fetch_one_row(
            connection.execute(
                """
                SELECT r.test_id, t.tenant_id, t.name AS test_name, t.interval_seconds, t.jitter_seconds,
                       t.down_after_failures, t.up_after_successes,
                       s.effective_ok, s.fail_streak, s.success_streak
                FROM runs r
                JOIN tests t ON t.id=r.test_id
                JOIN test_state s ON s.test_id=t.id
                WHERE r.id=? AND r.finished_at_ts IS NULL AND s.running_lock_id=r.id
                """,
                (run_id,),
            ),
        )
        if row is None:
            return _empty_outcome(run_id)
        return _complete_owned_run(
            connection,
            run_id,
            completion,
            completion_context(row_record(row)),
            now=utc_timestamp(),
        )


def complete_run(
    settings: RegistrySettings,
    *,
    run_id: str,
    completion: RunCompletion,
) -> CompletionOutcome:
    """Accept a completion only from the unfinished run that owns the active lock.

    Returns:
        The accepted transition, or an unchanged outcome for a stale run.

    Raises:
        ValueError: If the completion status is unsupported.
    """
    normalized_run_id = run_id.strip()
    if not normalized_run_id:
        return _empty_outcome(None)
    if completion.status not in _ALLOWED_COMPLETION_STATUSES:
        message = f"Unsupported completion status: {completion.status}"
        raise ValueError(message)
    with registry_connection(settings) as connection:
        return _complete_transaction(connection, normalized_run_id, completion)
