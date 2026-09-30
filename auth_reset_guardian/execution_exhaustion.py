# Copyright (c) 2026 PitchAI. All rights reserved.
"""Validate account-bound provider execution failures without logging lease identities."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict, cast

from .models import parse_timestamp, utc_iso

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from .models import AccountObservation


class ExecutionFailure(TypedDict):
    """Sanitized actual-execution proof, distinct from a broker scheduling outcome."""

    source: str
    error_code: str
    occurred_at: str
    received_at: str
    quota_windows: dict[str, dict[str, int]]


class BrokerExecutionDocument(TypedDict):
    """Unvalidated account-detail response from the broker JSON boundary."""

    state: object


class BrokerExecutionReport(TypedDict, total=False):
    """Named unvalidated fields of the opt-in broker evidence contract."""

    schema_version: object
    source: object
    error_code: object
    occurred_at: object
    received_at: object
    account_id: object
    lease_id: object
    client_name: object
    quota_windows: object


class QuotaWindowDocument(TypedDict):
    """Unvalidated quota-window member of an execution-evidence document."""

    quota_windows: object


def execution_failure_evidence(payload: BrokerExecutionDocument, *, account_id: str) -> ExecutionFailure | None:
    """Read only the versioned, explicit provider execution-error proof.

    Returns:
        Sanitized proof or none for missing, legacy, mismatched, or invalid evidence.
    """
    raw_state = payload.get("state")
    if not isinstance(raw_state, dict):
        return None
    raw_proof = cast("dict[str, object]", raw_state).get("execution_exhaustion")
    if not isinstance(raw_proof, dict):
        return None
    proof = cast("dict[str, object]", raw_proof)
    expected = {
        "schema_version": 1, "source": "provider_execution_error", "error_code": "usage_limit_reached",
        "account_id": account_id,
    }
    version = proof.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or any(
        proof.get(key) != value for key, value in expected.items()
    ):
        return None
    if not all(isinstance(proof.get(key), str) and str(proof[key]).strip() for key in ("lease_id", "client_name")):
        return None
    occurred = parse_timestamp(proof.get("occurred_at"), field_name="execution_exhaustion.occurred_at")
    received = parse_timestamp(proof.get("received_at"), field_name="execution_exhaustion.received_at")
    windows = _quota_windows(QuotaWindowDocument(quota_windows=proof.get("quota_windows")))
    if occurred > received or not windows:
        return None
    return ExecutionFailure(
        source="provider_execution_error", error_code="usage_limit_reached",
        occurred_at=utc_iso(occurred), received_at=utc_iso(received), quota_windows=windows,
    )


def proof_is_current(observation: AccountObservation, *, now: datetime, max_age: timedelta) -> bool:
    """Bind a sanitized execution failure to both fresh timestamps and exact epochs.

    Returns:
        True only while the original execution failure still describes these windows.
    """
    raw_proof = cast("object", observation.broker_state.get("execution_exhaustion"))
    if not isinstance(raw_proof, dict):
        return False
    proof = cast("dict[str, object]", raw_proof)
    if proof.get("source") != "provider_execution_error" or proof.get("error_code") != "usage_limit_reached":
        return False
    occurred = parse_timestamp(proof.get("occurred_at"), field_name="execution_exhaustion.occurred_at")
    received = parse_timestamp(proof.get("received_at"), field_name="execution_exhaustion.received_at")
    if not occurred <= received <= observation.captured_at <= now:
        return False
    if any(not 0 <= (now - value).total_seconds() <= max_age.total_seconds() for value in (occurred, received)):
        return False
    recorded = _quota_windows(QuotaWindowDocument(quota_windows=proof.get("quota_windows")))
    current = _quota_windows(QuotaWindowDocument(quota_windows=observation.usage_state))
    if not recorded or recorded != current:
        return False
    return all(
        window["reset_at"] - window["limit_window_seconds"] <= occurred.timestamp() < window["reset_at"]
        for window in current.values()
    )


def _quota_windows(document: QuotaWindowDocument) -> dict[str, dict[str, int]]:
    raw_windows = document["quota_windows"]
    if not isinstance(raw_windows, dict):
        return {}
    windows = cast("dict[str, object]", raw_windows)
    result: dict[str, dict[str, int]] = {}
    fields = ("limit_window_seconds", "reset_at")
    for name in ("primary_window", "secondary_window"):
        raw = windows.get(name)
        if raw is None:
            continue
        if not isinstance(raw, dict):
            return {}
        window = cast("dict[str, object]", raw)
        epoch: dict[str, int] = {}
        for key in fields:
            field = window.get(key)
            if isinstance(field, int) and not isinstance(field, bool) and field > 0:
                epoch[key] = field
        if len(epoch) != len(fields):
            return {}
        result[name] = epoch
    return result
