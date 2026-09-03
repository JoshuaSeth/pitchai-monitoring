# Copyright (c) 2026 PitchAI. All rights reserved.
"""First-projection grace proofs for scheduler-cell supervision."""

from __future__ import annotations

from .scheduler_cell_health import reduce_scheduler_cells
from .scheduler_cell_test_support import JEFF_BOOT_TWO, cell_observation
from .testing_runtime import pytest

_START = 1_788_370_133.001627


def test_new_boot_waits_for_first_projection_before_escalating() -> None:
    """Give a healthy new boot one freshness window to publish its first projection."""
    baseline = reduce_scheduler_cells((cell_observation(now=_START),), retained_cells={}, now=_START)
    first_heartbeat = cell_observation(now=_START + 1.0, boot_id=JEFF_BOOT_TWO)._replace(
        projection_sequence=0,
        projection_received_at=None,
        projection_received_at_ts=None,
    )
    grace = reduce_scheduler_cells((first_heartbeat,), retained_cells=baseline.cells, now=_START + 1.0)
    first_projection = reduce_scheduler_cells(
        (cell_observation(now=_START + 11.0, boot_id=JEFF_BOOT_TWO),),
        retained_cells=grace.cells,
        now=_START + 11.0,
    )
    still_missing = cell_observation(now=_START + 122.0, boot_id=JEFF_BOOT_TWO)._replace(
        projection_sequence=0,
        projection_received_at=None,
        projection_received_at_ts=None,
    )
    failed = reduce_scheduler_cells((still_missing,), retained_cells=grace.cells, now=_START + 122.0)

    if grace.events:
        pytest.fail(f"new boot escalated before its first projection window elapsed: {grace.events}")
    if first_projection.events:
        pytest.fail(f"first projection emitted a false recovery transition: {first_projection.events}")
    if [event.details.get("surface_kind") for event in failed.events] != ["projection_visibility"]:
        pytest.fail(f"persistently missing first projection was not escalated: {failed.events}")
