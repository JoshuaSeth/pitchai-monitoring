# Copyright (c) 2026 PitchAI. All rights reserved.
"""Transition, dedupe, cooldown, and synthetic proofs for hotpath incidents."""

from __future__ import annotations

import math
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from e2e_registry.hotpath_codec import decode_object
from e2e_registry.hotpath_store_read import build_hotpath_snapshot
from e2e_registry.hotpath_store_schema import connect, row_string
from e2e_registry.hotpath_store_write import ingest_report
from e2e_registry.hotpath_types import (
    SYNTHETIC_LANE_ID,
    SYNTHETIC_NAME,
    SYNTHETIC_PROJECT,
    SYNTHETIC_TARGET,
    HotpathReportRequest,
    load_inventory,
    validate_report_identity,
)

from .json_types import object_list, optional_object
from .testing_runtime import pytest

if TYPE_CHECKING:
    import sqlite3

    from e2e_registry.hotpath_store_models import IngestedReport
    from e2e_registry.hotpath_types import HotpathInventory, HotpathLane, JsonValue

_INVENTORY_PATH = Path(__file__).parents[1] / "e2e_registry" / "hotpath_inventory.json"
_SOURCE_SHA = "1" * 40
_DEPLOYED_SHA = "2" * 40
_ARTIFACT_SHA = "3" * 64
_CURRENT_REPORT_TS = 2000.0
_SYNTHETIC_PROOF_COUNT = 2


@dataclass(frozen=True)
class _ReportOptions:
    success: bool
    phase: str | None = None
    source_sha: str = _SOURCE_SHA
    synthetic: bool = False
    exercise_event_bus: bool = False


def _report(
    lane: HotpathLane,
    occurred_at_ts: float,
    options: _ReportOptions,
) -> HotpathReportRequest:
    lane_id = SYNTHETIC_LANE_ID if options.synthetic else lane.lane_id
    return HotpathReportRequest(
        artifact_receipt_sha256=_ARTIFACT_SHA,
        deployed_sha=_DEPLOYED_SHA,
        duration_seconds=17.25,
        evidence_uri=(
            "s3://pitchai-hotpath-artifacts/client-hotpaths/v1/"
            f"{lane_id}/{options.source_sha}/proof.json"
        ),
        exercise_event_bus=options.exercise_event_bus,
        failure_class=None if options.success else "assertion",
        failure_phase=None if options.success else (options.phase or "submit"),
        failure_reason=(
            None if options.success else "Expected persisted result was missing after reload."
        ),
        lane_id=lane_id,
        name=SYNTHETIC_NAME if options.synthetic else lane.name,
        occurred_at=datetime.fromtimestamp(occurred_at_ts, tz=UTC),
        project=SYNTHETIC_PROJECT if options.synthetic else lane.project,
        run_id=f"run-{occurred_at_ts:g}",
        schema_version=1,
        severity="info" if options.success else "critical",
        source_sha=options.source_sha,
        success=options.success,
        synthetic=options.synthetic,
        synthetic_scenario="safe-event-path-proof" if options.synthetic else None,
        target_surface=SYNTHETIC_TARGET if options.synthetic else lane.target_surface,
    )


def _ingest(
    db_path: Path,
    inventory: HotpathInventory,
    report: HotpathReportRequest,
    received_at_ts: float,
) -> IngestedReport:
    lane = validate_report_identity(report, inventory)
    return ingest_report(
        str(db_path),
        inventory,
        report,
        lane,
        received_at_ts=received_at_ts,
    )


def _outbox(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    query = (
        "SELECT event_kind, details_json, status "
        "FROM hotpath_event_outbox ORDER BY created_at_ts"
    )
    return cast(
        "list[sqlite3.Row]",
        connection.execute(query).fetchall(),
    )


def test_critical_transition_dedupes_changes_and_recovers(tmp_path: Path) -> None:
    """Emit only material RED transitions, cooldown repeats, and one recovery."""
    database = tmp_path / "hotpaths.sqlite3"
    inventory = load_inventory(str(_INVENTORY_PATH))
    lane = inventory.lanes[0]
    transitions = (
        (1000, _ReportOptions(success=False, phase="submit")),
        (1100, _ReportOptions(success=False, phase="submit")),
        (1200, _ReportOptions(success=False, phase="reload")),
        (3101, _ReportOptions(success=False, phase="reload")),
        (3200, _ReportOptions(success=True)),
    )
    reports = [_report(lane, timestamp, options) for timestamp, options in transitions]
    results: list[IngestedReport] = []
    for report, (timestamp, _) in zip(reports, transitions, strict=True):
        results.append(_ingest(database, inventory, report, timestamp))
    duplicate_result = _ingest(database, inventory, reports[0], 1001)
    actions = [result.receipt["event_action"] for result in results]
    if actions != [
        "queued_failure",
        "suppressed_cooldown",
        "queued_failure",
        "queued_failure",
        "queued_recovery",
    ]:
        pytest.fail(f"unexpected incident actions: {actions}")
    if (
        duplicate_result.duplicate is not True
        or duplicate_result.receipt != results[0].receipt
    ):
        pytest.fail("exact report retry did not return the original receipt")

    with closing(connect(str(database))) as connection:
        rows = _outbox(connection)
        if [row_string(row, "event_kind") for row in rows] != [
            "hotpath_red",
            "hotpath_red",
            "hotpath_red",
            "hotpath_recovered",
        ]:
            pytest.fail("unexpected outbox transitions")
        details: tuple[dict[str, JsonValue], ...] = (
            decode_object(row_string(rows[0], "details_json")),
            decode_object(row_string(rows[1], "details_json")),
            decode_object(row_string(rows[-1], "details_json")),
        )
    if details[0]["incident_fingerprint"] == details[1]["incident_fingerprint"]:
        pytest.fail("changed failed step did not change the material incident fingerprint")
    if details[2]["incident_fingerprint"] != details[1]["incident_fingerprint"]:
        pytest.fail("recovery did not close the exact latest material incident")
    if details[0]["alertable"] is not True or details[0]["repair_dispatch"] != "asap":
        pytest.fail("real critical failure is not eligible for ASAP incident response")
    if details[2]["critical"] is not True or details[2]["alertable"] is not True:
        pytest.fail("recovery cannot close the matching critical incident")
    if details[0]["project_id"] != lane.project or details[0]["artifact_links"] != [
        reports[0].evidence_uri,
    ]:
        pytest.fail("critical event lost exact project routing or evidence")


def test_out_of_order_and_synthetic_reports_never_replace_real_lane_state(tmp_path: Path) -> None:
    """Keep current lane state monotonic while retaining safe synthetic proofs."""
    database = tmp_path / "hotpaths.sqlite3"
    inventory = load_inventory(str(_INVENTORY_PATH))
    lane = inventory.lanes[0]
    _ = _ingest(database, inventory, _report(lane, 2000, _ReportOptions(success=True)), 2000)
    old_result = _ingest(database, inventory, _report(lane, 1900, _ReportOptions(success=False)), 2100)
    pass_result = _ingest(database, inventory, _report(lane, 2200, _ReportOptions(success=True, synthetic=True)), 2200)
    fail_result = _ingest(
        database,
        inventory,
        _report(
            lane,
            2300,
            _ReportOptions(success=False, synthetic=True, exercise_event_bus=True),
        ),
        2300,
    )
    snapshot = build_hotpath_snapshot(str(database), inventory, now_ts=2400)

    if old_result.receipt["event_action"] != "out_of_order":
        pytest.fail("out-of-order report was not retained without replacing state")
    if pass_result.receipt["event_action"] != "synthetic_only":
        pytest.fail("synthetic PASS should prove ingestion without an incident")
    if fail_result.receipt["event_action"] != "queued_synthetic_test":
        pytest.fail("synthetic FAIL did not exercise the safe event path")
    first_lane = object_list(snapshot["lanes"])[0]
    occurred_at = optional_object(first_lane["latest_report"])["occurred_at_ts"]
    timestamp_matches = (
        isinstance(occurred_at, (int, float))
        and not isinstance(occurred_at, bool)
        and math.isclose(float(occurred_at), _CURRENT_REPORT_TS)
    )
    if first_lane["status"] != "passing" or not timestamp_matches:
        pytest.fail("synthetic or old report replaced canonical real lane state")
    proofs = object_list(snapshot["synthetic_proofs"])
    if len(proofs) != _SYNTHETIC_PROOF_COUNT:
        pytest.fail(f"synthetic dashboard proof count is wrong: {len(proofs)}")
    with closing(connect(str(database))) as connection:
        rows = _outbox(connection)
        details = decode_object(row_string(rows[0], "details_json"))
    if details["test_event"] is not True or details["alertable"] is not False:
        pytest.fail("synthetic event was not explicitly suppressed from repair dispatch")


def test_source_and_deployed_material_state_control_fingerprint(tmp_path: Path) -> None:
    """Treat code revisions as material while ignoring receipt and run churn."""
    database = tmp_path / "hotpaths.sqlite3"
    inventory = load_inventory(str(_INVENTORY_PATH))
    lane = inventory.lanes[0]
    first = _report(lane, 3000, _ReportOptions(success=False))
    same_material = first.model_copy(
        update={
            "artifact_receipt_sha256": "4" * 64,
            "occurred_at": datetime.fromtimestamp(3010, tz=UTC),
            "run_id": "new-run",
        },
    )
    changed_source = _report(
        lane,
        3020,
        _ReportOptions(success=False, source_sha="5" * 40),
    )
    report_runs = ((first, 3000), (same_material, 3010), (changed_source, 3020))
    results: list[IngestedReport] = []
    for report, timestamp in report_runs:
        results.append(_ingest(database, inventory, report, timestamp))
    actions = [result.receipt["event_action"] for result in results]
    if actions != ["queued_failure", "suppressed_cooldown", "queued_failure"]:
        pytest.fail(f"material fingerprint behavior changed: {actions}")
