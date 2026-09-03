# Copyright (c) 2026 PitchAI. All rights reserved.
"""Contract tests for storage-aware scheduler incident events."""

from __future__ import annotations

from .scheduler_incident_feed import SchedulerIncidentCursor, scheduler_incident_page
from .scheduler_incident_test_support import incident_feed, recovery_feed
from .testing_runtime import pytest


def test_feed_event_preserves_per_cell_rejection_evidence() -> None:
    """Keep Jeff and main evidence explicit in the routed critical incident."""
    prior = SchedulerIncidentCursor(
        occurred_at="2026-09-02T16:00:00.000000Z",
        event_id=0,
    )
    page = scheduler_incident_page(incident_feed(), prior_cursor=prior)
    if len(page.events) != 1:
        pytest.fail(f"expected one scheduler transition, got {len(page.events)}")
    event = page.events[0]
    evidence = event.details.get("evidence")
    if event.kind != "production_failure" or not isinstance(evidence, list):
        pytest.fail("scheduler failure did not become one critical production event")
    rendered = "\n".join(str(item) for item in evidence)
    if "dev-jeff-cell-two rejected" not in rendered or "dev-main-cell-one rejected" not in rendered:
        pytest.fail(f"per-cell rejection evidence was lost: {rendered}")
    if "/mnt/pitchai-dev-data" not in rendered or "separate-device" not in rendered:
        pytest.fail(f"storage-root rejection evidence was lost: {rendered}")
    if event.details.get("owner_project") != "pitchai_cli_new":
        pytest.fail("scheduler incident was not routed to its CLI/app-server owner")


def test_feed_recovery_links_completed_create_to_exact_failure() -> None:
    """Close the same incident only after durable cell completion proof."""
    initial = SchedulerIncidentCursor(
        occurred_at="2026-09-02T16:00:00.000000Z",
        event_id=0,
    )
    failure_page = scheduler_incident_page(incident_feed(), prior_cursor=initial)
    recovery_page = scheduler_incident_page(recovery_feed(), prior_cursor=failure_page.next_cursor)
    if len(failure_page.events) != 1 or len(recovery_page.events) != 1:
        pytest.fail("scheduler failure/recovery fixture did not yield one transition each")
    failure = failure_page.events[0]
    recovery = recovery_page.events[0]
    if failure.kind != "production_failure" or recovery.kind != "production_recovered":
        pytest.fail(f"scheduler transition kinds are invalid: {failure.kind}, {recovery.kind}")
    if failure.details.get("incident_key") != recovery.details.get("incident_key"):
        pytest.fail("scheduler recovery did not retain the original incident key")
    if failure.details.get("incident_fingerprint") != recovery.details.get("incident_fingerprint"):
        pytest.fail("scheduler recovery did not retain the exact failure fingerprint")
    evidence = recovery.details.get("evidence")
    if not isinstance(evidence, list) or not any("dev-jeff-cell-two" in str(item) for item in evidence):
        pytest.fail(f"scheduler recovery lost assigned-cell proof: {evidence}")
