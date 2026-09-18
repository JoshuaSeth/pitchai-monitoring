# Copyright (c) 2026 PitchAI. All rights reserved.
"""Transactional ingestion and incident decisions for hotpath reports."""

from __future__ import annotations

import hashlib
from contextlib import closing
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .hotpath_codec import canonical_json
from .hotpath_store_models import IncidentDecision, IngestedReport, PersistenceReceipt, StateUpdate
from .hotpath_store_records import (
    event_intent_id,
    existing_receipt,
    insert_event_intent,
    insert_report,
    load_lane_state,
    upsert_lane_state,
)
from .hotpath_store_schema import connect, ensure_schema

if TYPE_CHECKING:
    import sqlite3

    from .hotpath_store_models import LaneState
    from .hotpath_types import HotpathInventory, HotpathLane, HotpathReportRequest, JsonValue


def ingest_report(
    db_path: str,
    inventory: HotpathInventory,
    report: HotpathReportRequest,
    lane: HotpathLane | None,
    *,
    received_at_ts: float,
) -> IngestedReport:
    """Insert one immutable report and incident intent atomically.

    Returns:
        A deterministic server receipt and duplicate marker.
    """
    ensure_schema(db_path)
    with closing(connect(db_path)) as connection:
        _ = connection.execute("BEGIN IMMEDIATE")
        ingested = _persist_report(connection, inventory, report, lane, received_at_ts)
        _ = connection.execute("COMMIT")
        return ingested


def _persist_report(
    connection: sqlite3.Connection,
    inventory: HotpathInventory,
    report: HotpathReportRequest,
    lane: HotpathLane | None,
    received_at_ts: float,
) -> IngestedReport:
    canonical_report = canonical_json(report.canonical_payload())
    canonical_digest = hashlib.sha256(canonical_report.encode()).hexdigest()
    report_id = f"hotpath-v1-{canonical_digest}"
    duplicate = existing_receipt(connection, report_id)
    if duplicate is not None:
        return IngestedReport(receipt=duplicate, duplicate=True)
    previous = load_lane_state(connection, report.lane_id) if not report.synthetic else None
    decision = _decide(report, previous, inventory.incident_cooldown_seconds, received_at_ts)
    intent_id = event_intent_id(report_id, decision.event_kind) if decision.event_kind else None
    receipt = _build_receipt(
        report_id,
        canonical_digest,
        decision.action,
        intent_id,
        received_at_ts,
    )
    receipt_hash = hashlib.sha256(canonical_json(receipt).encode()).hexdigest()
    receipt["report_receipt_sha256"] = receipt_hash
    persistence = PersistenceReceipt(
        report_id=report_id,
        canonical_report=canonical_report,
        receipt_json=canonical_json(receipt),
        receipt_hash=receipt_hash,
        received_at_ts=received_at_ts,
    )
    insert_report(connection, report, persistence, decision)
    if decision.update_state:
        upsert_lane_state(connection, report, persistence, decision)
    if decision.event_kind is not None:
        insert_event_intent(connection, report, lane, persistence, decision)
    return IngestedReport(receipt=receipt, duplicate=False)


def _decide(
    report: HotpathReportRequest,
    previous: LaneState | None,
    cooldown_seconds: int,
    received_at_ts: float,
) -> IncidentDecision:
    fingerprint = None if report.success else _failure_fingerprint(report)
    if report.synthetic:
        event_kind = "hotpath_red" if report.exercise_event_bus and not report.success else None
        action = "queued_synthetic_test" if event_kind else "synthetic_only"
        return IncidentDecision(
            action=action,
            event_kind=event_kind,
            fingerprint=fingerprint,
            event_fingerprint=fingerprint if event_kind else None,
            update_state=False,
            next_state=StateUpdate(0, 0, None, None),
        )
    if previous is not None and report.occurred_at.timestamp() <= previous.latest_occurred_at_ts:
        return IncidentDecision(
            action="out_of_order",
            event_kind=None,
            fingerprint=fingerprint,
            event_fingerprint=None,
            update_state=False,
            next_state=_unchanged_state(previous),
        )
    fail_streak = 0 if report.success else (previous.fail_streak + 1 if previous else 1)
    success_streak = (previous.success_streak + 1 if previous else 1) if report.success else 0
    event_kind, action, event_fingerprint = _incident_transition(
        report,
        previous,
        fingerprint,
        cooldown_seconds,
        received_at_ts,
    )
    last_fingerprint, last_event_at = _next_incident_state(
        previous,
        event_kind,
        event_fingerprint,
        received_at_ts,
    )
    return IncidentDecision(
        action=action,
        event_kind=event_kind,
        fingerprint=fingerprint,
        event_fingerprint=event_fingerprint,
        update_state=True,
        next_state=StateUpdate(fail_streak, success_streak, last_fingerprint, last_event_at),
    )


def _incident_transition(
    report: HotpathReportRequest,
    previous: LaneState | None,
    fingerprint: str | None,
    cooldown_seconds: int,
    received_at_ts: float,
) -> tuple[str | None, str, str | None]:
    if report.success:
        if previous is None or previous.current_success:
            return None, "none", None
        if previous.last_event_fingerprint:
            return "hotpath_recovered", "queued_recovery", previous.last_event_fingerprint
        return None, "recovered_without_incident", None
    if report.severity != "critical":
        if previous is not None and previous.last_event_fingerprint:
            return (
                "hotpath_recovered",
                "queued_recovery_to_warning",
                previous.last_event_fingerprint,
            )
        return None, "warning_only", None
    changed = previous is None or previous.current_success or previous.last_event_fingerprint != fingerprint
    cooldown_elapsed = previous is None or previous.last_event_at_ts is None
    if previous is not None and previous.last_event_at_ts is not None:
        cooldown_elapsed = received_at_ts - previous.last_event_at_ts >= cooldown_seconds
    if changed or cooldown_elapsed:
        transition = ("hotpath_red", "queued_failure", fingerprint)
    else:
        transition = (None, "suppressed_cooldown", None)
    return transition


def _next_incident_state(
    previous: LaneState | None,
    event_kind: str | None,
    event_fingerprint: str | None,
    received_at_ts: float,
) -> tuple[str | None, float | None]:
    if event_kind == "hotpath_red":
        return event_fingerprint, received_at_ts
    if event_kind == "hotpath_recovered":
        return None, None
    if previous is None:
        return None, None
    return previous.last_event_fingerprint, previous.last_event_at_ts


def _unchanged_state(previous: LaneState) -> StateUpdate:
    return StateUpdate(
        previous.fail_streak,
        previous.success_streak,
        previous.last_event_fingerprint,
        previous.last_event_at_ts,
    )


def _build_receipt(
    report_id: str,
    canonical_digest: str,
    event_action: str,
    intent_id: str | None,
    received_at_ts: float,
) -> dict[str, JsonValue]:
    received_at = datetime.fromtimestamp(received_at_ts, tz=UTC).isoformat(timespec="microseconds")
    return {
        "canonical_report_sha256": canonical_digest,
        "event_action": event_action,
        "event_intent_id": intent_id,
        "received_at": received_at.replace("+00:00", "Z"),
        "report_id": report_id,
        "schema_version": 1,
    }


def _failure_fingerprint(report: HotpathReportRequest) -> str:
    reason = " ".join((report.failure_reason or "").lower().split())[:1000]
    material_state: dict[str, JsonValue] = {
        "deployed_sha": report.deployed_sha,
        "failure_class": report.failure_class,
        "failure_phase": report.failure_phase,
        "failure_reason": reason,
        "lane_id": report.lane_id,
        "severity": report.severity,
        "source_sha": report.source_sha,
        "target_surface": report.target_surface,
    }
    return hashlib.sha256(canonical_json(material_state).encode()).hexdigest()
