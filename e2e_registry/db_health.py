# Copyright (c) 2026 PitchAI. All rights reserved.
"""Validated health-state transitions for completed E2E runs."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from e2e_registry.models import (
    InvalidRegistryDataError,
    require_integer,
    require_text,
)

if TYPE_CHECKING:
    import sqlite3

    from e2e_registry.models import (
        DatabaseRecord,
        DatabaseScalar,
    )


class CompletionContext(NamedTuple):
    """Persisted test and health values needed to complete one run."""

    test_id: str
    tenant_id: str
    test_name: str
    interval_seconds: int
    jitter_seconds: int
    down_after_failures: int
    up_after_successes: int
    effective_ok: bool
    fail_streak: int
    success_streak: int


class HealthTransition(NamedTuple):
    """Debounced state produced by one health observation."""

    effective_ok: bool
    fail_streak: int
    success_streak: int
    alerted_down: bool
    recovered_up: bool


def persisted_effective_ok(value: DatabaseScalar) -> bool:
    """Decode the canonical persisted boolean representation.

    Returns:
        The exact persisted health value.

    Raises:
        InvalidRegistryDataError: If the value is not zero or one.
    """
    if value in {0, "0"}:
        return False
    if value in {1, "1"}:
        return True
    message = "effective_ok must be persisted as 0 or 1"
    raise InvalidRegistryDataError(message)


def completion_context(record: DatabaseRecord) -> CompletionContext:
    """Validate the persisted values required by completion.

    Returns:
        A typed completion context.
    """
    return CompletionContext(
        test_id=require_text(record.get("test_id"), label="test_id"),
        tenant_id=require_text(record.get("tenant_id"), label="tenant_id"),
        test_name=require_text(record.get("test_name"), label="test_name"),
        interval_seconds=max(
            1,
            require_integer(record.get("interval_seconds"), label="interval_seconds"),
        ),
        jitter_seconds=max(
            0,
            require_integer(record.get("jitter_seconds"), label="jitter_seconds"),
        ),
        down_after_failures=max(
            1,
            require_integer(
                record.get("down_after_failures"),
                label="down_after_failures",
            ),
        ),
        up_after_successes=max(
            1,
            require_integer(
                record.get("up_after_successes"),
                label="up_after_successes",
            ),
        ),
        effective_ok=persisted_effective_ok(record.get("effective_ok")),
        fail_streak=require_integer(record.get("fail_streak"), label="fail_streak"),
        success_streak=require_integer(
            record.get("success_streak"),
            label="success_streak",
        ),
    )


def update_effective_ok(
    context: CompletionContext,
    *,
    observed_ok: bool,
) -> HealthTransition:
    """Apply debounce thresholds to one observed result.

    Returns:
        The next health state and any threshold transitions.
    """
    if observed_ok:
        success_streak = context.success_streak + 1
        fail_streak = 0
    else:
        fail_streak = context.fail_streak + 1
        success_streak = 0
    if context.effective_ok:
        effective_ok = fail_streak < context.down_after_failures
    else:
        effective_ok = success_streak >= context.up_after_successes
    return HealthTransition(
        effective_ok=effective_ok,
        fail_streak=fail_streak,
        success_streak=success_streak,
        alerted_down=context.effective_ok and not effective_ok,
        recovered_up=not context.effective_ok and effective_ok,
    )


def persist_observed_state(
    connection: sqlite3.Connection,
    context: CompletionContext,
    *,
    observed_ok: bool,
    now: float,
) -> HealthTransition:
    """Persist and return a debounced health observation.

    Returns:
        The persisted health transition.
    """
    transition = update_effective_ok(context, observed_ok=observed_ok)
    parameters = (
        int(transition.effective_ok),
        transition.fail_streak,
        transition.success_streak,
        now,
        context.test_id,
    )
    if observed_ok:
        connection.execute(
            """
            UPDATE test_state
            SET effective_ok=?, fail_streak=?, success_streak=?, last_ok_ts=?
            WHERE test_id=?
            """,
            parameters,
        )
    else:
        connection.execute(
            """
            UPDATE test_state
            SET effective_ok=?, fail_streak=?, success_streak=?, last_fail_ts=?
            WHERE test_id=?
            """,
            parameters,
        )
    return transition
