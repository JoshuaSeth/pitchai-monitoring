# Copyright (c) 2026 PitchAI. All rights reserved.
"""Contract proof for the canonical client hotpath inventory and reports."""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

from e2e_registry.hotpath_types import (
    SYNTHETIC_LANE_ID,
    SYNTHETIC_NAME,
    SYNTHETIC_PROJECT,
    SYNTHETIC_TARGET,
    HotpathReportRequest,
    load_inventory,
    validate_report_identity,
)

from .json_types import float_value, json_object
from .testing_runtime import pytest

if TYPE_CHECKING:
    from .json_types import JsonInput, JsonObject

_INVENTORY_PATH = Path(__file__).parents[1] / "e2e_registry" / "hotpath_inventory.json"
_SOURCE_SHA = "a" * 40
_ARTIFACT_SHA = "b" * 64
_DURATION_SECONDS = 12.5
_EXPECTED_INTERVAL_SECONDS = 172_800
_STALE_AFTER_SECONDS = 259_200
_INCIDENT_COOLDOWN_SECONDS = 1_800
_REQUIRED_NAMES = {
    "AFASAsk / GZB",
    "AIGENDA Business Rules",
    "AIGENDA calendar",
    "AIPC / SkyBuyFly",
    "Apologetica CMS",
    "AutoPAR",
    "CISNL Maatje",
    "DFT formative assessment",
    "DePlanBook CMS",
    "DePlanBook Play",
    "Orthoparse",
    "QuickChat RSR",
    "potAIto / Aardappelprijs",
}


def _report_payload(*, success: bool = True) -> JsonObject:
    inventory = load_inventory(str(_INVENTORY_PATH))
    lane = inventory.lanes[0]
    raw: JsonInput = {
        "artifact_receipt_sha256": _ARTIFACT_SHA,
        "duration_seconds": _DURATION_SECONDS,
        "evidence_uri": (
            "s3://pitchai-hotpath-artifacts/client-hotpaths/v1/"
            f"{lane.lane_id}/{_SOURCE_SHA}/receipt.json"
        ),
        "failure_class": None if success else "assertion",
        "failure_phase": None if success else "persistence-read",
        "failure_reason": None if success else "Saved answer was not visible after reload.",
        "lane_id": lane.lane_id,
        "name": lane.name,
        "occurred_at": "2026-08-27T18:00:00Z",
        "project": lane.project,
        "run_id": "manual-contract-proof-1",
        "schema_version": 1,
        "severity": "info" if success else "critical",
        "source_sha": _SOURCE_SHA,
        "success": success,
        "target_surface": lane.target_surface,
    }
    return json_object(raw)


def test_inventory_is_the_exact_reviewed_thirteen_lane_set() -> None:
    """Keep every discovered lane, tag, reminder, and timing policy canonical."""
    inventory = load_inventory(str(_INVENTORY_PATH))
    names = {lane.name for lane in inventory.lanes}
    reminder_ids = {lane.reminder_id for lane in inventory.lanes}
    agent_ids = {lane.agent_global_id for lane in inventory.lanes}
    if len(inventory.lanes) != len(_REQUIRED_NAMES) or names != _REQUIRED_NAMES:
        pytest.fail(f"unexpected hotpath inventory: {sorted(names)}")
    if len(reminder_ids) != len(_REQUIRED_NAMES) or len(agent_ids) != len(_REQUIRED_NAMES):
        pytest.fail("hotpath reminders and agents must be one-to-one with lanes")
    if inventory.canonical_tag != "hot-path-testing":
        pytest.fail(f"unexpected hotpath tag: {inventory.canonical_tag}")
    if inventory.expected_interval_seconds != _EXPECTED_INTERVAL_SECONDS:
        pytest.fail("hotpath reminder cadence must remain two days")
    if (
        inventory.stale_after_seconds != _STALE_AFTER_SECONDS
        or inventory.incident_cooldown_seconds != _INCIDENT_COOLDOWN_SECONDS
    ):
        pytest.fail("hotpath freshness or incident cooldown changed unexpectedly")


def test_real_report_binds_to_inventory_and_canonical_private_evidence() -> None:
    """Accept a complete report only when its caller identity matches inventory."""
    inventory = load_inventory(str(_INVENTORY_PATH))
    report = HotpathReportRequest.model_validate(_report_payload())
    lane = validate_report_identity(report, inventory)
    if lane is None or lane.lane_id != report.lane_id:
        pytest.fail("valid canonical report did not bind to its lane")
    payload = report.canonical_payload()
    duration = float_value(payload["duration_seconds"])
    if (
        payload["source_sha"] != _SOURCE_SHA
        or duration is None
        or not math.isclose(duration, _DURATION_SECONDS)
    ):
        pytest.fail("canonical payload lost required monitoring fields")


def test_report_semantics_fail_closed() -> None:
    """Reject incomplete failures, public evidence, and unsafe event exercises."""
    cases: list[tuple[JsonObject, str]] = [
        ({"failure_reason": None}, "requires failure_reason"),
        ({"severity": "info"}, "must be warning or critical"),
        ({"evidence_uri": "https://example.invalid/proof"}, "canonical private SeaweedFS prefix"),
        ({"exercise_event_bus": True}, "reserved for safe synthetic proof"),
    ]
    for changes, message in cases:
        payload = _report_payload(success=False)
        payload.update(changes)
        with pytest.raises(ValueError) as captured:
            _ = HotpathReportRequest.model_validate(payload)
        if message not in str(captured.value):
            pytest.fail(f"missing validation detail {message!r}: {captured.value}")


def test_synthetic_identity_is_reserved_and_cannot_impersonate_real_state() -> None:
    """Bind safe protocol exercises to the dedicated non-production lane."""
    payload = _report_payload()
    payload.update(
        {
            "evidence_uri": (
                "s3://pitchai-hotpath-artifacts/client-hotpaths/v1/"
                f"{SYNTHETIC_LANE_ID}/{_SOURCE_SHA}/pass.json"
            ),
            "lane_id": SYNTHETIC_LANE_ID,
            "name": SYNTHETIC_NAME,
            "project": SYNTHETIC_PROJECT,
            "synthetic": True,
            "synthetic_scenario": "safe-pass-proof",
            "target_surface": SYNTHETIC_TARGET,
        },
    )
    report = HotpathReportRequest.model_validate(payload)
    if validate_report_identity(report, load_inventory(str(_INVENTORY_PATH))) is not None:
        pytest.fail("synthetic proof unexpectedly resolved to a real lane")
