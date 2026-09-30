# Copyright (c) 2026 PitchAI. All rights reserved.
"""Offline proof that shared ownership preserves distinct practice result state."""

from pathlib import Path
from typing import TYPE_CHECKING

from .hotpath_contract_runtime import HOTPATH_REPORT_MODEL, HOTPATH_TYPES
from .hotpath_store_runtime import HOTPATH_READ, HOTPATH_WRITE
from .json_types import object_list
from .testing_runtime import pytest

if TYPE_CHECKING:
    from .json_types import JsonObject

_INVENTORY_PATH = Path(__file__).parents[1] / "e2e_registry" / "hotpath_inventory.json"


def test_shared_worker_has_exact_targets_and_two_existing_reminders() -> None:
    """Bind the two practice identities without replacing the Wadd duty."""
    inventory = HOTPATH_TYPES.load_inventory(str(_INVENTORY_PATH))
    lanes = {lane.lane_id: lane for lane in inventory.lanes}
    owner = "5dc4b437-1c3b-5a18-92f8-ca7f79142a0f"
    practice_reminder = "reminder-central-c73278a5-4325-4286-9632-a204ab9a3717"
    expected = {
        "ridderkerk": (
            "Orthodontie Ridderkerk",
            "www.orthodontieridderkerk.nl",
            "ortho_ridderkerk",
        ),
        "walburg": ("Orthodontie Walburg", "orthowalburg.nl", "ortho_walburg"),
    }
    for client, (name, domain, tenant) in expected.items():
        lane = lanes[f"quickchat-{client}-hotpath-monitor"]
        if (lane.agent_global_id, lane.reminder_id, lane.project) != (
            owner,
            practice_reminder,
            "quickchat",
        ):
            pytest.fail(
                "practice reports must use the existing shared worker and reminder",
            )
        target = f"{domain} with the embedded chat.pitchai.net/chat_mini/{tenant}/start?floating=false frame"
        if (lane.name, lane.primary_domain, lane.target_surface) != (
            name,
            domain,
            target,
        ):
            pytest.fail("production client/tenant target drifted")
    wadd = lanes["quickchat-waddinxveen-hotpath-monitor"]
    if (
        wadd.agent_global_id != owner
        or wadd.reminder_id != "reminder-central-b08f59c4-ef94-40fc-96e0-91257817ce5b"
    ):
        pytest.fail("Waddinxveen ownership or original daily duty changed")
    if "quickchat-rsr-hotpath-monitor" in lanes:
        pytest.fail("RSR must remain retired")


def test_practice_admission_is_unreported_and_results_do_not_cross_clients(
    tmp_path: Path,
) -> None:
    """Keep fixture reports isolated from production and from the other tenant."""
    inventory = HOTPATH_TYPES.load_inventory(str(_INVENTORY_PATH))
    lanes = {lane.lane_id: lane for lane in inventory.lanes}
    ridderkerk = lanes["quickchat-ridderkerk-hotpath-monitor"]
    walburg = lanes["quickchat-walburg-hotpath-monitor"]
    db = tmp_path / "isolated-practice-test.sqlite3"
    # These fixtures stay exclusively in a temporary local store; no HTTP submission.
    payload: JsonObject = {
        "schema_version": 1,
        "lane_id": ridderkerk.lane_id,
        "project": ridderkerk.project,
        "name": ridderkerk.name,
        "target_surface": ridderkerk.target_surface,
        "occurred_at": "2026-09-30T00:00:00Z",
        "source_sha": "a" * 40,
        "success": False,
        "severity": "critical",
        "failure_reason": "Offline fixture failure",
        "evidence_uri": (
            f"s3://pitchai-hotpath-artifacts/client-hotpaths/v1/"
            f"{ridderkerk.lane_id}/{'a' * 40}/audit-receipt.json"
        ),
        "duration_seconds": 1,
        "artifact_receipt_sha256": "b" * 64,
        "run_id": "offline-fixture",
    }
    first = HOTPATH_REPORT_MODEL.model_validate(payload)
    wrong_payload = first.canonical_payload()
    wrong_payload["target_surface"] = walburg.target_surface
    with pytest.raises(ValueError):
        HOTPATH_TYPES.validate_report_identity(
            HOTPATH_REPORT_MODEL.model_validate(wrong_payload), inventory,
        )
    before = HOTPATH_READ.build_hotpath_snapshot(str(db), inventory, now_ts=2000)
    for row in object_list(before["lanes"]):
        if row["status"] != "never_reported" or row["latest_report"] is not None:
            pytest.fail("registration must not manufacture a report")
    HOTPATH_WRITE.ingest_report(
        str(db), inventory, first, ridderkerk, received_at_ts=2000,
    )
    after = HOTPATH_READ.build_hotpath_snapshot(str(db), inventory, now_ts=2001)
    rows = object_list(after["lanes"])
    states = {str(row["lane_id"]): row for row in rows}
    if states[ridderkerk.lane_id]["status"] != "critical":
        pytest.fail("Ridderkerk result did not route to its own row")
    if states[walburg.lane_id]["status"] != "never_reported":
        pytest.fail("shared worker result leaked into Walburg")
    payload.update(
        lane_id=walburg.lane_id,
        name=walburg.name,
        target_surface=walburg.target_surface,
        success=True,
        severity="info",
        failure_reason=None,
        evidence_uri=(
            f"s3://pitchai-hotpath-artifacts/client-hotpaths/v1/"
            f"{walburg.lane_id}/{'a' * 40}/audit-receipt.json"
        ),
    )
    second = HOTPATH_REPORT_MODEL.model_validate(payload)
    HOTPATH_WRITE.ingest_report(
        str(db), inventory, second, walburg, received_at_ts=2002,
    )
    after = HOTPATH_READ.build_hotpath_snapshot(str(db), inventory, now_ts=2003)
    rows = object_list(after["lanes"])
    states = {str(row["lane_id"]): row for row in rows}
    if (
        states[ridderkerk.lane_id]["status"] != "critical"
        or states[walburg.lane_id]["status"] != "passing"
    ):
        pytest.fail("client result states were combined")
