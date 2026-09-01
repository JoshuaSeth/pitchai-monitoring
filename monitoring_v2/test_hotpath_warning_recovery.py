# Copyright (c) 2026 PitchAI. All rights reserved.
"""Regression proof for warning-only hotpath recovery transitions."""

from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .hotpath_contract_runtime import HOTPATH_REPORT_MODEL, HOTPATH_TYPES
from .hotpath_store_runtime import HOTPATH_SCHEMA, HOTPATH_WRITE
from .json_types import json_object
from .testing_runtime import pytest

if TYPE_CHECKING:
    from .hotpath_contract_runtime import HotpathLane, HotpathReport
    from .json_types import JsonInput

_INVENTORY_PATH = Path(__file__).parents[1] / "e2e_registry" / "hotpath_inventory.json"


def _report(lane: HotpathLane, timestamp: float, *, success: bool) -> HotpathReport:
    severity = "info" if success else "warning"
    raw: JsonInput = {
        "artifact_receipt_sha256": "3" * 64,
        "deployed_sha": "2" * 40,
        "duration_seconds": 17.25,
        "evidence_uri": (
            "s3://pitchai-hotpath-artifacts/client-hotpaths/v1/"
            f"{lane.lane_id}/{'1' * 40}/proof.json"
        ),
        "exercise_event_bus": False,
        "failure_class": None if success else "setup_dependency",
        "failure_phase": None if success else "browser_launch",
        "failure_reason": None if success else "Browser dependency is unavailable.",
        "lane_id": lane.lane_id,
        "name": lane.name,
        "occurred_at": datetime.fromtimestamp(timestamp, tz=UTC).isoformat(),
        "project": lane.project,
        "run_id": f"warning-recovery-{timestamp:g}",
        "schema_version": 1,
        "severity": severity,
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
        str(database), inventory, warning, lane, received_at_ts=1000,
    )
    recovery_result = HOTPATH_WRITE.ingest_report(
        str(database), inventory, recovery, lane, received_at_ts=1100,
    )

    if warning_result.receipt["event_action"] != "warning_only":
        pytest.fail("warning failure unexpectedly opened a critical incident")
    if recovery_result.receipt["event_action"] != "recovered_without_incident":
        pytest.fail("warning recovery did not retain the no-incident distinction")
    with closing(HOTPATH_SCHEMA.connect(str(database))) as connection:
        if connection.execute("SELECT 1 FROM hotpath_event_outbox").fetchone() is not None:
            pytest.fail("warning-only transition emitted an Events Bus incident")
