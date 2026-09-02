# Copyright (c) 2026 PitchAI. All rights reserved.
"""Historical and edge-case proofs for scheduler-cell supervision."""

from __future__ import annotations

from .json_types import text_value, value_list
from .scheduler_cell_health import reduce_scheduler_cells
from .scheduler_cell_test_support import JEFF_BOOT_ONE, JEFF_BOOT_TWO, MAIN_BOOT, cell_observation
from .testing_runtime import pytest

_JEFF_LAST_HEARTBEAT = 1_788_371_867.0
_JEFF_OUTAGE_DETECTED = 1_788_372_227.0
_JEFF_RECOVERY_HEARTBEAT = 1_788_372_251.0
_DIRECT_REQUESTED = 1_788_370_138.099890
_DIRECT_LAG_OBSERVED = 1_788_370_720.0
_DIRECT_ACCEPTED = 1_788_370_720.871474
_DIRECT_DELIVERED = 1_788_370_133.001627


def test_six_minute_jeff_outage_emits_failure_and_new_boot_recovery() -> None:
    """Detect the observed 17:57-18:04 heartbeat gap and its fenced restart."""
    healthy = reduce_scheduler_cells(
        (cell_observation(now=_JEFF_LAST_HEARTBEAT),),
        retained_cells={},
        now=_JEFF_LAST_HEARTBEAT,
    )
    stale = cell_observation(
        now=_JEFF_OUTAGE_DETECTED,
        last_received_at=_JEFF_LAST_HEARTBEAT,
        boot_id=JEFF_BOOT_ONE,
    )
    failed = reduce_scheduler_cells((stale,), retained_cells=healthy.cells, now=_JEFF_OUTAGE_DETECTED)
    recovered_cell = cell_observation(now=_JEFF_RECOVERY_HEARTBEAT, boot_id=JEFF_BOOT_TWO)
    recovered = reduce_scheduler_cells(
        (recovered_cell,),
        retained_cells=failed.cells,
        now=_JEFF_RECOVERY_HEARTBEAT,
    )

    if [event.kind for event in failed.events] != ["production_failure"]:
        pytest.fail(f"Jeff heartbeat gap did not open one failure: {failed.events}")
    if [event.kind for event in recovered.events] != ["production_recovered"]:
        pytest.fail(f"Jeff restart did not recover the open failure: {recovered.events}")
    failure_evidence = "\n".join(str(value) for value in value_list(failed.events[0].details.get("evidence")))
    recovery_evidence = "\n".join(str(value) for value in value_list(recovered.events[0].details.get("evidence")))
    if JEFF_BOOT_ONE not in failure_evidence or JEFF_BOOT_TWO not in recovery_evidence:
        pytest.fail("old-boot outage and new-boot recovery evidence was not preserved")
    if failed.events[0].details.get("incident_fingerprint") != recovered.events[0].details.get(
        "incident_fingerprint",
    ):
        pytest.fail("recovery did not link to the exact open cell incident")


def test_direct_reminder_acceptance_delay_emits_failure_and_recovery() -> None:
    """Expose the historical roughly ten-minute requested-to-accepted delay."""
    baseline = reduce_scheduler_cells(
        (cell_observation(now=_DIRECT_REQUESTED),),
        retained_cells={},
        now=_DIRECT_REQUESTED,
    )
    lag_seconds = _DIRECT_LAG_OBSERVED - _DIRECT_REQUESTED
    delayed = cell_observation(
        now=_DIRECT_LAG_OBSERVED,
        pressure_updates={
            "direct_unaccepted_work_count": 1,
            "direct_unaccepted_requested_count": 0,
            "direct_unaccepted_dispatching_count": 1,
            "direct_unaccepted_oldest_age_seconds": lag_seconds,
        },
    )
    failed = reduce_scheduler_cells((delayed,), retained_cells=baseline.cells, now=_DIRECT_LAG_OBSERVED)
    cleared = reduce_scheduler_cells(
        (cell_observation(now=_DIRECT_ACCEPTED),),
        retained_cells=failed.cells,
        now=_DIRECT_ACCEPTED,
    )

    if [event.kind for event in failed.events] != ["production_failure"]:
        pytest.fail(f"direct acceptance delay was not escalated: {failed.events}")
    if failed.events[0].details.get("surface_kind") != "direct_delivery_lag":
        pytest.fail("direct acceptance incident used the wrong condition")
    if "581.9s" not in text_value(failed.events[0].details.get("reason")):
        pytest.fail("direct acceptance incident lost its observed age")
    if [event.kind for event in cleared.events] != ["production_recovered"]:
        pytest.fail("accepted direct work did not recover its incident")


def test_fresh_heartbeat_with_stale_projection_is_independently_visible() -> None:
    """Detect a projection adapter stall even while heartbeat supervision stays green."""
    baseline = reduce_scheduler_cells(
        (cell_observation(now=_DIRECT_DELIVERED),),
        retained_cells={},
        now=_DIRECT_DELIVERED,
    )
    stale_projection = cell_observation(now=_DIRECT_LAG_OBSERVED)._replace(
        projection_sequence=41414,
        projection_received_at="2026-09-02T17:28:53.001627Z",
        projection_received_at_ts=_DIRECT_DELIVERED,
    )
    failed = reduce_scheduler_cells(
        (stale_projection,),
        retained_cells=baseline.cells,
        now=_DIRECT_LAG_OBSERVED,
    )
    recovered = reduce_scheduler_cells(
        (cell_observation(now=_DIRECT_ACCEPTED),),
        retained_cells=failed.cells,
        now=_DIRECT_ACCEPTED,
    )

    if [event.details.get("surface_kind") for event in failed.events] != ["projection_visibility"]:
        pytest.fail(f"stale central projection was not isolated: {failed.events}")
    if [event.kind for event in recovered.events] != ["production_recovered"]:
        pytest.fail("fresh central projection receipt did not recover")


def test_locked_direct_observation_escalates_after_grace_without_cell_disk_state() -> None:
    """Keep SQLite-lock or ENOSPC observation loss visible from the remote observer."""
    start = _DIRECT_REQUESTED
    baseline = reduce_scheduler_cells((cell_observation(now=start),), retained_cells={}, now=start)
    unavailable = cell_observation(
        now=start + 1.0,
        pressure_updates={"direct_unaccepted_observation_ready": 0},
    )
    grace = reduce_scheduler_cells((unavailable,), retained_cells=baseline.cells, now=start + 1.0)
    still_unavailable = cell_observation(
        now=start + 62.0,
        pressure_updates={"direct_unaccepted_observation_ready": 0},
    )
    failed = reduce_scheduler_cells((still_unavailable,), retained_cells=grace.cells, now=start + 62.0)
    recovered = reduce_scheduler_cells(
        (cell_observation(now=start + 63.0),),
        retained_cells=failed.cells,
        now=start + 63.0,
    )

    if grace.events:
        pytest.fail("one bounded SQLite read miss bypassed the observation grace")
    if [event.kind for event in failed.events] != ["production_failure"]:
        pytest.fail("persistent direct observation loss was not escalated")
    if [event.kind for event in recovered.events] != ["production_recovered"]:
        pytest.fail("restored direct observation did not recover")


def test_declared_ready_direct_observation_rejects_missing_samples() -> None:
    """Do not silently treat a partial direct-delivery metric set as healthy."""
    start = _DIRECT_REQUESTED
    baseline = reduce_scheduler_cells((cell_observation(now=start),), retained_cells={}, now=start)
    partial = cell_observation(
        now=start + 1.0,
        pressure_updates={"direct_unaccepted_work_count": "missing"},
    )
    grace = reduce_scheduler_cells((partial,), retained_cells=baseline.cells, now=start + 1.0)
    still_partial = cell_observation(
        now=start + 62.0,
        pressure_updates={"direct_unaccepted_work_count": "missing"},
    )
    failed = reduce_scheduler_cells((still_partial,), retained_cells=grace.cells, now=start + 62.0)

    if grace.events:
        pytest.fail("one incomplete metric sample bypassed the observation grace")
    if [event.kind for event in failed.events] != ["production_failure"]:
        pytest.fail(f"persistent partial direct metrics were silently healthy: {failed.events}")
    event = failed.events[0]
    if event.details.get("surface_kind") != "direct_delivery_observation":
        pytest.fail(f"partial direct metrics opened the wrong incident: {event.details}")
    if "missing or malformed" not in text_value(event.details.get("reason")):
        pytest.fail("partial direct-metric diagnostics did not identify their contract failure")


def test_master_root_enospc_preserves_healthy_second_disk_in_event_evidence() -> None:
    """Distinguish root slash failure from a spacious selected work-storage root."""
    main = cell_observation(
        now=_JEFF_LAST_HEARTBEAT,
        slug="dev-main-cell-one",
        boot_id=MAIN_BOOT,
        pressure_updates={
            "master_service_host": 1,
            "root_disk_used_percent": 100.0,
            "root_disk_free_bytes": 0,
            "work_storage_used_percent": 77.0,
            "work_storage_free_bytes": 218 * 1024**3,
            "work_storage_same_device_as_root": 0,
        },
    )
    reduction = reduce_scheduler_cells((main,), retained_cells={}, now=_JEFF_LAST_HEARTBEAT)

    storage_events = [event for event in reduction.events if event.details.get("surface_kind") == "storage_capacity"]
    if len(storage_events) != 1:
        pytest.fail(f"main root ENOSPC did not emit one storage event: {reduction.events}")
    event = storage_events[0]
    evidence = "\n".join(str(value) for value in value_list(event.details.get("evidence")))
    if "root=/ used=100.0% free=0.0GiB" not in evidence:
        pytest.fail(f"root slash capacity was not preserved: {evidence}")
    if "new_lane_storage=/mnt/pitchai-dev-data" not in evidence or "free=218.0GiB" not in evidence:
        pytest.fail(f"roomy second-disk evidence was not preserved: {evidence}")
    if "must protect root" not in text_value(event.details.get("reason")):
        pytest.fail("master-node second-disk protection was not actionable")
