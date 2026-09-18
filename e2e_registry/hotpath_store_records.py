# Copyright (c) 2026 PitchAI. All rights reserved.
"""SQLite records for hotpath reports, lane state, and event intents."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, cast

from .hotpath_codec import canonical_json, decode_object
from .hotpath_store_models import LaneState
from .hotpath_store_schema import (
    HotpathStateError,
    row_float,
    row_integer,
    row_optional_string,
    row_string,
    row_value,
)

if TYPE_CHECKING:
    import sqlite3

    from .hotpath_store_models import IncidentDecision, PersistenceReceipt
    from .hotpath_types import HotpathLane, HotpathReportRequest, JsonValue


def existing_receipt(connection: sqlite3.Connection, report_id: str) -> dict[str, JsonValue] | None:
    """Return an idempotent receipt when the exact report already exists.

    Returns:
        The original receipt, or ``None`` when this report is new.
    """
    row = cast(
        "sqlite3.Row | None",
        connection.execute(
            "SELECT receipt_json FROM hotpath_reports WHERE report_id = ?",
            (report_id,),
        ).fetchone(),
    )
    return None if row is None else decode_object(row_string(row, "receipt_json"))


def load_lane_state(connection: sqlite3.Connection, lane_id: str) -> LaneState | None:
    """Load the transition state for one canonical lane.

    Returns:
        The current state, or ``None`` before the first report.
    """
    row = cast(
        "sqlite3.Row | None",
        connection.execute(
            "SELECT * FROM hotpath_lane_state WHERE lane_id = ?",
            (lane_id,),
        ).fetchone(),
    )
    if row is None:
        return None
    raw_last_event_at = row_value(row, "last_event_at_ts")
    last_event_at = (
        float(raw_last_event_at)
        if isinstance(raw_last_event_at, int | float) and not isinstance(raw_last_event_at, bool)
        else None
    )
    return LaneState(
        current_success=bool(row_integer(row, "current_success")),
        latest_occurred_at_ts=row_float(row, "latest_occurred_at_ts"),
        fail_streak=row_integer(row, "fail_streak"),
        success_streak=row_integer(row, "success_streak"),
        last_event_fingerprint=row_optional_string(row, "last_event_fingerprint"),
        last_event_at_ts=last_event_at,
    )


def insert_report(
    connection: sqlite3.Connection,
    report: HotpathReportRequest,
    persistence: PersistenceReceipt,
    decision: IncidentDecision,
) -> None:
    """Insert one immutable normalized report row."""
    _ = connection.execute(
        """INSERT INTO hotpath_reports VALUES (
        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )""",
        (
            persistence.report_id,
            report.schema_version,
            report.lane_id,
            report.project,
            report.name,
            report.target_surface,
            report.occurred_at.timestamp(),
            persistence.received_at_ts,
            report.source_sha,
            report.deployed_sha,
            int(report.success),
            report.severity,
            report.failure_reason,
            report.failure_class,
            report.failure_phase,
            report.evidence_uri,
            report.duration_seconds,
            report.artifact_receipt_sha256,
            report.run_id,
            int(report.synthetic),
            report.synthetic_scenario,
            int(report.exercise_event_bus),
            decision.fingerprint,
            decision.action,
            persistence.canonical_report,
            persistence.receipt_json,
            persistence.receipt_hash,
        ),
    )


def upsert_lane_state(
    connection: sqlite3.Connection,
    report: HotpathReportRequest,
    persistence: PersistenceReceipt,
    decision: IncidentDecision,
) -> None:
    """Replace current canonical state after a strictly newer report."""
    state = decision.next_state
    _ = connection.execute(
        "INSERT OR REPLACE INTO hotpath_lane_state VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            report.lane_id,
            persistence.report_id,
            report.occurred_at.timestamp(),
            int(report.success),
            report.severity,
            decision.fingerprint,
            state.fail_streak,
            state.success_streak,
            state.last_event_fingerprint,
            state.last_event_at_ts,
        ),
    )


def insert_event_intent(
    connection: sqlite3.Connection,
    report: HotpathReportRequest,
    lane: HotpathLane | None,
    persistence: PersistenceReceipt,
    decision: IncidentDecision,
) -> None:
    """Persist the typed event intent in the report transaction.

    Raises:
        HotpathStateError: If the incident decision omits its event kind or fingerprint.
    """
    if decision.event_kind is None:
        error = "event intent requires an event kind"
        raise HotpathStateError(error)
    if not decision.event_fingerprint:
        error = "event intent requires an incident fingerprint"
        raise HotpathStateError(error)
    details = _event_details(report, lane, persistence, decision)
    intent_id = event_intent_id(persistence.report_id, decision.event_kind)
    _ = connection.execute(
        """INSERT INTO hotpath_event_outbox (
        intent_id, report_id, event_kind, occurred_at_ts, details_json, status, created_at_ts, updated_at_ts
        ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
        (
            intent_id,
            persistence.report_id,
            decision.event_kind,
            report.occurred_at.timestamp(),
            canonical_json(details),
            persistence.received_at_ts,
            persistence.received_at_ts,
        ),
    )


def _event_details(
    report: HotpathReportRequest,
    lane: HotpathLane | None,
    persistence: PersistenceReceipt,
    decision: IncidentDecision,
) -> dict[str, JsonValue]:
    owner_project = lane.project if lane else "pitchai_monitoring"
    reason = (report.failure_reason or "Hotpath recovered to its expected production behavior.")[:800]
    return {
        "affected_apps": [report.project],
        "affected_service": report.project,
        "affected_surface": report.target_surface,
        "agent_global_id": lane.agent_global_id if lane else None,
        "alertable": not report.synthetic,
        "artifact_receipt_sha256": report.artifact_receipt_sha256,
        "artifact_links": [report.evidence_uri],
        "artifact_uri": report.evidence_uri,
        "artifact_url": report.evidence_uri,
        "critical": True,
        "dashboard_url": "https://monitoring.pitchai.net/dashboard#hotpaths",
        "deployed_sha": report.deployed_sha,
        "deployment_hint": report.target_surface,
        "domain": lane.primary_domain if lane else "monitoring.pitchai.net",
        "duration_seconds": report.duration_seconds,
        "evidence": [report.evidence_uri],
        "evidence_uri": report.evidence_uri,
        "event_contract_version": 1,
        "expected_behavior": lane.expected_behavior if lane else "Exercise the safe synthetic route only.",
        "failed_steps": [report.failure_phase] if report.failure_phase else [],
        "failure_class": report.failure_class,
        "failure_phase": report.failure_phase,
        "failure_reason": report.failure_reason,
        "hotpath_id": report.lane_id,
        "hotpath_name": report.name,
        "incident_fingerprint": decision.event_fingerprint,
        "incident_key": f"hotpath:{report.lane_id}",
        "lane_id": report.lane_id,
        "monitoring_report_id": persistence.report_id,
        "monitoring_receipt_sha256": persistence.receipt_hash,
        "name": report.name,
        "owner_project": owner_project,
        "project": report.project,
        "project_id": owner_project,
        "project_group": owner_project,
        "reason": reason,
        "reminder_id": lane.reminder_id if lane else None,
        "repair_dispatch": "test_only" if report.synthetic else "asap",
        "run_id": report.run_id,
        "service": report.project,
        "severity": report.severity,
        "site": report.target_surface,
        "source_sha": report.source_sha,
        "suppressed": False,
        "synthetic": report.synthetic,
        "synthetic_scenario": report.synthetic_scenario,
        "target_surface": report.target_surface,
        "target_environment": "production",
        "test_event": report.synthetic,
    }


def event_intent_id(report_id: str, event_kind: str) -> str:
    """Build the deterministic persisted intent identity.

    Returns:
        A namespaced SHA-256 identity.
    """
    digest = hashlib.sha256(f"{report_id}:{event_kind}".encode()).hexdigest()
    return f"hotpath-intent-{digest}"
