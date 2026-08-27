# Copyright (c) 2026 PitchAI. All rights reserved.
"""HTTP boundary proof for authenticated hotpath reports and summaries."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from e2e_registry.hotpath_types import (
    SYNTHETIC_LANE_ID,
    SYNTHETIC_NAME,
    SYNTHETIC_PROJECT,
    SYNTHETIC_TARGET,
    load_inventory,
)

from .dashboard_server import running_dashboard_server
from .json_types import json_object, object_list, optional_object
from .network_gateway import exercise_hotpath_api
from .testing_runtime import pytest

if TYPE_CHECKING:
    from .json_types import JsonInput, JsonObject
    from .testing_runtime import MonkeyPatch

_INVENTORY_PATH = Path(__file__).parents[1] / "e2e_registry" / "hotpath_inventory.json"
_REPORTER_TOKEN = "test-hotpath-reporter-token-" + ("x" * 40)
_SOURCE_SHA = "a" * 40
_ARTIFACT_SHA = "b" * 64
_HTTP_OK = 200
_HTTP_UNAUTHORIZED = 401
_HTTP_FORBIDDEN = 403


def _report_payload(*, synthetic: bool, success: bool) -> JsonObject:
    inventory = load_inventory(str(_INVENTORY_PATH))
    lane = inventory.lanes[0]
    lane_id = SYNTHETIC_LANE_ID if synthetic else lane.lane_id
    occurred_at = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    raw: JsonInput = {
        "artifact_receipt_sha256": _ARTIFACT_SHA,
        "deployed_sha": "c" * 40,
        "duration_seconds": 9.75,
        "evidence_uri": (
            "s3://pitchai-hotpath-artifacts/client-hotpaths/v1/"
            f"{lane_id}/{_SOURCE_SHA}/api-proof.json"
        ),
        "exercise_event_bus": synthetic and not success,
        "failure_class": None if success else "synthetic_assertion",
        "failure_phase": None if success else "event-path",
        "failure_reason": None if success else "Intentional safe synthetic FAIL proof.",
        "lane_id": lane_id,
        "name": SYNTHETIC_NAME if synthetic else lane.name,
        "occurred_at": occurred_at,
        "project": SYNTHETIC_PROJECT if synthetic else lane.project,
        "run_id": "manual-api-proof" if not synthetic else "synthetic-api-proof",
        "schema_version": 1,
        "severity": "info" if success else "critical",
        "source_sha": _SOURCE_SHA,
        "success": success,
        "synthetic": synthetic,
        "synthetic_scenario": "safe-fail-event-path-proof" if synthetic else None,
        "target_surface": SYNTHETIC_TARGET if synthetic else lane.target_surface,
    }
    return json_object(raw)


def _body(response_text: str) -> JsonObject:
    return json_object(cast("JsonInput", json.loads(response_text)))


@pytest.mark.asyncio
async def test_report_route_auth_idempotency_state_and_safe_event_intent(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Prove real PASS plus non-alertable synthetic FAIL through protected HTTP."""
    monkeypatch.setenv("E2E_HOTPATH_REPORTER_TOKEN", _REPORTER_TOKEN)
    with running_dashboard_server(tmp_path) as server:
        receipts = await exercise_hotpath_api(
            server,
            _report_payload(synthetic=False, success=True),
            _report_payload(synthetic=True, success=False),
            _REPORTER_TOKEN,
        )
    if receipts.anonymous.status_code != _HTTP_UNAUTHORIZED or receipts.wrong_token.status_code != _HTTP_FORBIDDEN:
        pytest.fail("hotpath report route accepted absent or invalid reporter authentication")
    if receipts.accepted.status_code != _HTTP_OK or receipts.synthetic.status_code != _HTTP_OK:
        pytest.fail(f"hotpath reports were rejected: {receipts.accepted.text} / {receipts.synthetic.text}")
    accepted_body = _body(receipts.accepted.text)
    duplicate_body = _body(receipts.duplicate.text)
    if accepted_body.get("duplicate") is not False or duplicate_body.get("duplicate") is not True:
        pytest.fail("hotpath report idempotency receipt changed across exact retry")
    if optional_object(accepted_body.get("receipt")) != optional_object(
        duplicate_body.get("receipt"),
    ):
        pytest.fail("exact hotpath retry did not return the original receipt")
    if receipts.summary.status_code != _HTTP_OK:
        pytest.fail(f"protected hotpath summary failed: {receipts.summary.text}")
    snapshot = optional_object(_body(receipts.summary.text).get("hotpaths"))
    lanes = object_list(snapshot.get("lanes"))
    proofs = object_list(snapshot.get("synthetic_proofs"))
    first_lane = lanes[0] if lanes else {}
    if first_lane.get("status") != "passing":
        pytest.fail("accepted real hotpath PASS was not visible in current lane state")
    if len(proofs) != 1 or proofs[0].get("event_action") != "queued_synthetic_test":
        pytest.fail("safe synthetic FAIL did not remain visible with a queued event intent")
