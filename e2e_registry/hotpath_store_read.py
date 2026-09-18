# Copyright (c) 2026 PitchAI. All rights reserved.
"""Read-only dashboard projection over persisted hotpath state."""

from __future__ import annotations

from contextlib import closing
from typing import TYPE_CHECKING, cast

from .hotpath_store_schema import (
    connect,
    ensure_schema,
    row_float,
    row_integer,
    row_optional_string,
    row_string,
)

if TYPE_CHECKING:
    import sqlite3

    from .hotpath_types import HotpathInventory, HotpathLane, JsonValue


def build_hotpath_snapshot(
    db_path: str,
    inventory: HotpathInventory,
    *,
    now_ts: float,
) -> dict[str, JsonValue]:
    """Return every canonical lane, latest evidence, and delivery posture.

    Returns:
        The complete dashboard-safe hotpath projection.
    """
    ensure_schema(db_path)
    with closing(connect(db_path)) as connection:
        return _snapshot_from_connection(connection, inventory, now_ts)


def _snapshot_from_connection(
    connection: sqlite3.Connection,
    inventory: HotpathInventory,
    now_ts: float,
) -> dict[str, JsonValue]:
    latest = _latest_by_lane(connection)
    lanes = [_lane_projection(lane, latest.get(lane.lane_id), inventory, now_ts) for lane in inventory.lanes]
    lane_values: list[JsonValue] = []
    lane_values.extend(lanes)
    counts, status = _count_statuses(lanes)
    return {
        "canonical_tag": inventory.canonical_tag,
        "counts": counts,
        "event_delivery": _event_delivery(connection),
        "expected_interval_seconds": inventory.expected_interval_seconds,
        "generated_at_ts": now_ts,
        "incident_cooldown_seconds": inventory.incident_cooldown_seconds,
        "inventory_reviewed_at": inventory.reviewed_at,
        "lanes": lane_values,
        "schema_version": inventory.schema_version,
        "stale_after_seconds": inventory.stale_after_seconds,
        "status": status,
        "synthetic_proofs": _synthetic_proofs(connection),
    }


def _latest_by_lane(connection: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = cast(
        "list[sqlite3.Row]",
        connection.execute(
            """SELECT state.*, report.project, report.name, report.target_surface,
            report.received_at_ts, report.source_sha, report.deployed_sha,
            report.failure_reason, report.failure_class, report.failure_phase,
            report.evidence_uri, report.duration_seconds, report.artifact_receipt_sha256,
            report.run_id, report.event_action, report.report_receipt_sha256
            FROM hotpath_lane_state AS state
            JOIN hotpath_reports AS report ON report.report_id = state.latest_report_id""",
        ).fetchall(),
    )
    output: dict[str, sqlite3.Row] = {}
    for row in rows:
        output[row_string(row, "lane_id")] = row
    return output


def _lane_projection(
    lane: HotpathLane,
    row: sqlite3.Row | None,
    inventory: HotpathInventory,
    now_ts: float,
) -> dict[str, JsonValue]:
    base: dict[str, JsonValue] = {
        "agent_global_id": lane.agent_global_id,
        "expected_behavior": lane.expected_behavior,
        "lane_id": lane.lane_id,
        "name": lane.name,
        "project": lane.project,
        "reminder_id": lane.reminder_id,
        "target_surface": lane.target_surface,
    }
    if row is None:
        return {**base, "age_seconds": None, "latest_report": None, "status": "never_reported"}
    occurred_at_ts = row_float(row, "latest_occurred_at_ts")
    age_seconds = max(0.0, now_ts - occurred_at_ts)
    success = bool(row_integer(row, "current_success"))
    severity = row_string(row, "current_severity")
    status = (
        "stale"
        if age_seconds > inventory.stale_after_seconds
        else _report_status(
            success=success,
            severity=severity,
        )
    )
    latest_report: dict[str, JsonValue] = {
        "artifact_receipt_sha256": row_string(row, "artifact_receipt_sha256"),
        "deployed_sha": row_optional_string(row, "deployed_sha"),
        "duration_seconds": row_float(row, "duration_seconds"),
        "event_action": row_string(row, "event_action"),
        "evidence_uri": row_string(row, "evidence_uri"),
        "fail_streak": row_integer(row, "fail_streak"),
        "failure_class": row_optional_string(row, "failure_class"),
        "failure_phase": row_optional_string(row, "failure_phase"),
        "failure_reason": row_optional_string(row, "failure_reason"),
        "occurred_at_ts": occurred_at_ts,
        "received_at_ts": row_float(row, "received_at_ts"),
        "report_id": row_string(row, "latest_report_id"),
        "report_receipt_sha256": row_string(row, "report_receipt_sha256"),
        "run_id": row_string(row, "run_id"),
        "severity": severity,
        "source_sha": row_string(row, "source_sha"),
        "success": success,
        "success_streak": row_integer(row, "success_streak"),
    }
    return {**base, "age_seconds": age_seconds, "latest_report": latest_report, "status": status}


def _count_statuses(lanes: list[dict[str, JsonValue]]) -> tuple[dict[str, JsonValue], str]:
    passing = sum(item.get("status") == "passing" for item in lanes)
    warning = sum(item.get("status") == "warning" for item in lanes)
    critical = sum(item.get("status") == "critical" for item in lanes)
    stale = sum(item.get("status") == "stale" for item in lanes)
    never_reported = sum(item.get("status") == "never_reported" for item in lanes)
    counts: dict[str, JsonValue] = {
        "critical": critical,
        "never_reported": never_reported,
        "passing": passing,
        "stale": stale,
        "total": len(lanes),
        "warning": warning,
    }
    if critical:
        return counts, "critical"
    return counts, "attention" if warning or stale or never_reported else "healthy"


def _event_delivery(connection: sqlite3.Connection) -> dict[str, JsonValue]:
    rows = cast(
        "list[sqlite3.Row]",
        connection.execute(
            "SELECT status, COUNT(*) AS count FROM hotpath_event_outbox GROUP BY status",
        ).fetchall(),
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row_string(row, "status")] = row_integer(row, "count")
    return {
        "delivered": counts.get("delivered", 0),
        "delivering": counts.get("delivering", 0),
        "pending": counts.get("pending", 0),
        "retrying": counts.get("retrying", 0),
    }


def _synthetic_proofs(connection: sqlite3.Connection) -> list[JsonValue]:
    rows = cast(
        "list[sqlite3.Row]",
        connection.execute(
            """SELECT report.*, event.status AS delivery_status, event.receiver_event_id
            FROM hotpath_reports AS report
            LEFT JOIN hotpath_event_outbox AS event ON event.report_id = report.report_id
            WHERE report.synthetic = 1 ORDER BY report.received_at_ts DESC LIMIT 12""",
        ).fetchall(),
    )
    output: list[JsonValue] = [
        {
            "delivery_status": row_optional_string(row, "delivery_status"),
            "event_action": row_string(row, "event_action"),
            "occurred_at_ts": row_float(row, "occurred_at_ts"),
            "receiver_event_id": row_optional_string(row, "receiver_event_id"),
            "report_id": row_string(row, "report_id"),
            "report_receipt_sha256": row_string(row, "report_receipt_sha256"),
            "scenario": row_optional_string(row, "synthetic_scenario"),
            "success": bool(row_integer(row, "success")),
        }
        for row in rows
    ]
    return output


def _report_status(*, success: bool, severity: str) -> str:
    if success:
        return "passing"
    return "critical" if severity == "critical" else "warning"
