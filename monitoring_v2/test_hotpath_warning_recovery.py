# Copyright (c) 2026 PitchAI. All rights reserved.
"""Regression proof for warning-only hotpath recovery transitions."""

from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .hotpath_contract_runtime import HOTPATH_REPORT_MODEL, HOTPATH_TYPES
from .hotpath_store_runtime import HOTPATH_CODEC, HOTPATH_SCHEMA, HOTPATH_WRITE
from .json_types import json_object
from .testing_runtime import pytest

if TYPE_CHECKING:
    import sqlite3

    from .hotpath_contract_runtime import HotpathLane, HotpathReport
    from .json_types import JsonInput

_INVENTORY_PATH = Path(__file__).parents[1] / "e2e_registry" / "hotpath_inventory.json"


def _report(
    lane: HotpathLane,
    timestamp: float,
    *,
    success: bool,
    severity: str | None = None,
) -> HotpathReport:
    report_severity = severity or ("info" if success else "warning")
    raw: JsonInput = {
        "artifact_receipt_sha256": "3" * 64,
        "deployed_sha": "2" * 40,
        "duration_seconds": 17.25,
        "evidence_uri": (f"s3://pitchai-hotpath-artifacts/client-hotpaths/v1/{lane.lane_id}/{'1' * 40}/proof.json"),
        "exercise_event_bus": False,
        "failure_class": None
        if success
        else (
            "authentication_and_availability_regression"
            if report_severity == "critical"
            else "synthetic_authorization_absent"
        ),
        "failure_phase": None
        if success
        else ("combined_environment_verdict" if report_severity == "critical" else "synthetic_write_boundary"),
        "failure_reason": None
        if success
        else (
            "Production authentication or availability failed."
            if report_severity == "critical"
            else "Read-only checks passed; isolated synthetic authorization is absent."
        ),
        "lane_id": lane.lane_id,
        "name": lane.name,
        "occurred_at": datetime.fromtimestamp(timestamp, tz=UTC).isoformat(),
        "project": lane.project,
        "run_id": f"warning-recovery-{timestamp:g}",
        "schema_version": 1,
        "severity": report_severity,
        "source_sha": "1" * 40,
        "success": success,
        "synthetic": False,
        "synthetic_scenario": None,
        "target_surface": lane.target_surface,
    }
    return HOTPATH_REPORT_MODEL.model_validate(json_object(raw))


def test_warning_recovery_does_not_emit_unidentifiable_incident(tmp_path: Path) -> None:
    """Do not create a critical recovery when no critical incident was opened."""
    database = tmp_path / "hotpaths.sqlite3"
    inventory = HOTPATH_TYPES.load_inventory(str(_INVENTORY_PATH))
    lane = inventory.lanes[0]
    warning = _report(lane, 1000, success=False)
    recovery = _report(lane, 1100, success=True)

    warning_result = HOTPATH_WRITE.ingest_report(
        str(database),
        inventory,
        warning,
        lane,
        received_at_ts=1000,
    )
    recovery_result = HOTPATH_WRITE.ingest_report(
        str(database),
        inventory,
        recovery,
        lane,
        received_at_ts=1100,
    )

    if warning_result.receipt["event_action"] != "warning_only":
        pytest.fail("warning failure unexpectedly opened a critical incident")
    if recovery_result.receipt["event_action"] != "recovered_without_incident":
        pytest.fail("warning recovery did not retain the no-incident distinction")
    with closing(HOTPATH_SCHEMA.connect(str(database))) as connection:
        if connection.execute("SELECT 1 FROM hotpath_event_outbox").fetchone() is not None:
            pytest.fail("warning-only transition emitted an Events Bus incident")


def test_critical_downgrade_to_warning_closes_incident_exactly_once(tmp_path: Path) -> None:
    """Resolve the old critical incident without promoting a coverage warning."""
    database = tmp_path / "hotpaths.sqlite3"
    inventory = HOTPATH_TYPES.load_inventory(str(_INVENTORY_PATH))
    lane = inventory.lanes[0]
    reports = (
        (_report(lane, 1000, success=False, severity="critical"), 1000),
        (_report(lane, 1100, success=False), 1100),
        (_report(lane, 1200, success=False), 1200),
        (_report(lane, 1300, success=True), 1300),
    )

    results = [
        HOTPATH_WRITE.ingest_report(
            str(database),
            inventory,
            report,
            lane,
            received_at_ts=timestamp,
        )
        for report, timestamp in reports[:2]
    ]
    with closing(HOTPATH_SCHEMA.connect(str(database))) as connection:
        warning_state = cast(
            "sqlite3.Row | None",
            connection.execute(
                "SELECT current_success, current_severity, last_event_fingerprint, "
                "last_event_at_ts FROM hotpath_lane_state WHERE lane_id = ?",
                (lane.lane_id,),
            ).fetchone(),
        )
    if warning_state is None:
        pytest.fail("warning lane state disappeared")
    if (
        HOTPATH_SCHEMA.row_integer(warning_state, "current_success") != 0
        or HOTPATH_SCHEMA.row_string(warning_state, "current_severity") != "warning"
        or HOTPATH_SCHEMA.row_optional_string(warning_state, "last_event_fingerprint") is not None
        or HOTPATH_SCHEMA.row_value(warning_state, "last_event_at_ts") is not None
    ):
        pytest.fail("coverage warning did not clear the resolved critical identity")
    results.extend(
        HOTPATH_WRITE.ingest_report(
            str(database),
            inventory,
            report,
            lane,
            received_at_ts=timestamp,
        )
        for report, timestamp in reports[2:]
    )

    actions = [result.receipt["event_action"] for result in results]
    if actions != [
        "queued_failure",
        "queued_recovery_to_warning",
        "warning_only",
        "recovered_without_incident",
    ]:
        pytest.fail(f"unexpected critical-to-warning actions: {actions}")
    with closing(HOTPATH_SCHEMA.connect(str(database))) as connection:
        rows = cast(
            "list[sqlite3.Row]",
            connection.execute(
                "SELECT event_kind, details_json FROM hotpath_event_outbox ORDER BY created_at_ts",
            ).fetchall(),
        )
        state = cast(
            "sqlite3.Row | None",
            connection.execute(
                "SELECT current_success, current_severity, last_event_fingerprint, "
                "last_event_at_ts FROM hotpath_lane_state WHERE lane_id = ?",
                (lane.lane_id,),
            ).fetchone(),
        )
    if [HOTPATH_SCHEMA.row_string(row, "event_kind") for row in rows] != [
        "hotpath_red",
        "hotpath_recovered",
    ]:
        pytest.fail("critical-to-warning transition emitted duplicate or missing events")
    red = HOTPATH_CODEC.decode_object(HOTPATH_SCHEMA.row_string(rows[0], "details_json"))
    recovery = HOTPATH_CODEC.decode_object(HOTPATH_SCHEMA.row_string(rows[1], "details_json"))
    if recovery["incident_fingerprint"] != red["incident_fingerprint"]:
        pytest.fail("warning recovery did not close the exact critical fingerprint")
    if state is None:
        pytest.fail("lane state disappeared")
    if (
        HOTPATH_SCHEMA.row_integer(state, "current_success") != 1
        or HOTPATH_SCHEMA.row_string(state, "current_severity") != "info"
        or HOTPATH_SCHEMA.row_optional_string(state, "last_event_fingerprint") is not None
        or HOTPATH_SCHEMA.row_value(state, "last_event_at_ts") is not None
    ):
        pytest.fail("resolved critical incident remained active in lane state")
