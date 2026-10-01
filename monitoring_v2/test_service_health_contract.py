# Copyright (c) 2026 PitchAI. All rights reserved.
"""Keep the shared monitoring worker health decision table meaningful and bounded."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .service_health_model import (
    STATUS_DEGRADED,
    STATUS_HEALTHY,
    STATUS_STARTING,
    STATUS_UNHEALTHY,
)
from .service_health_request import parse_request
from .service_health_roles import probe
from .testing_documents import monitor_document, role_documents, runner_document
from .testing_runtime import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from .json_types import JsonObject
    from .service_health_model import HealthReport

_NOW = 1_800_000_000.0
_BOOTED_LONG_AGO = _NOW - 1_000.0
_BOOTED_BEFORE_A_LONG_JOB = _NOW - 25_000.0
_JUST_BOOTED = _NOW - 1.0
_FRESH_AGES = {
    "monitor": 30.0,
    "runner": 5.0,
    "database-dependency": 60.0,
    "scheduler-observer": 10.0,
    "domain-incident": 10.0,
}
_STALE_AGES = {
    "monitor": 700.0,
    "runner": 200.0,
    "database-dependency": 1_000.0,
    "scheduler-observer": 200.0,
    "domain-incident": 200.0,
}
_STALE_REASONS = {
    "monitor": "monitor_progress_stale",
    "runner": "runner_poll_stale",
    "database-dependency": "collector_progress_stale",
    "scheduler-observer": "observer_progress_stale",
    "domain-incident": "producer_progress_stale",
}
_MISSING_REASONS = {
    "monitor": "state_missing",
    "runner": "runner_heartbeat_missing",
    "database-dependency": "collector_state_missing",
    "scheduler-observer": "observer_state_missing",
    "domain-incident": "producer_state_missing",
}
_STAMP_TARGETS = {
    "monitor": (("", "updated_at"),),
    "runner": (("", "updated_at_ts"),),
    "database-dependency": (
        ("", "generated_at_ts"),
        ("collector", "observed_at_ts"),
        ("collector", "last_successful_cycle_at_ts"),
    ),
    "scheduler-observer": (("", "updated_at_ts"),),
    "domain-incident": (("producer", "updated_at_ts"),),
}


def _probe_document(
    role: str,
    document: JsonObject | None,
    tmp_path: Path,
    *,
    start_epoch: float | None = _BOOTED_LONG_AGO,
) -> HealthReport:
    """Return the evaluated report for one written retained document."""
    evidence = tmp_path / f"{role}.json"
    if document is not None:
        _ = evidence.write_text(json.dumps(document), encoding="utf-8")
    request = parse_request(["--role", role, "--evidence", str(evidence)])
    return probe(request, now=_NOW, start_epoch=start_epoch)


def _without_progress_stamp(role: str, document: JsonObject) -> JsonObject:
    """Return the retained document with its progress stamps cleared."""
    for section, key in _STAMP_TARGETS[role]:
        nested = document if not section else document.get(section)
        if isinstance(nested, dict):
            nested[key] = None
    return document


def test_fresh_progress_keeps_every_worker_role_healthy(tmp_path: Path) -> None:
    """Keep every deployed worker role healthy while its retained progress is fresh."""
    for role, document in role_documents(now=_NOW, ages=_FRESH_AGES).items():
        report = _probe_document(role, document, tmp_path)
        if report.status != STATUS_HEALTHY or report.exit_code != 0:
            pytest.fail(f"{role} fresh progress was not healthy: {report.render()}")


def test_absent_evidence_is_bounded_startup_not_death(tmp_path: Path) -> None:
    """Report an absent state document as startup inside grace, then unhealthy."""
    for role, expected_reason in _MISSING_REASONS.items():
        starting = _probe_document(role, None, tmp_path, start_epoch=_JUST_BOOTED)
        if starting.status != STATUS_STARTING or starting.exit_code != 0:
            pytest.fail(f"{role} absent evidence was not a bounded startup: {starting.render()}")
        if starting.reason != expected_reason:
            pytest.fail(f"{role} startup reason changed: {starting.render()}")
        expired = _probe_document(role, None, tmp_path, start_epoch=_BOOTED_LONG_AGO)
        if expired.status != STATUS_UNHEALTHY or expired.exit_code != 1:
            pytest.fail(f"{role} absent evidence never expired its grace: {expired.render()}")


def test_stale_progress_is_unhealthy_with_the_role_reason(tmp_path: Path) -> None:
    """Report stale retained progress as unhealthy with a role-specific reason."""
    for role, document in role_documents(now=_NOW, ages=_STALE_AGES).items():
        report = _probe_document(role, document, tmp_path)
        if report.status != STATUS_UNHEALTHY or report.restart_required is not True:
            pytest.fail(f"{role} stale progress was not unhealthy: {report.render()}")
        if report.reason != _STALE_REASONS[role]:
            pytest.fail(f"{role} stale reason changed: {report.render()}")


def test_malformed_progress_is_unhealthy_and_actionable(tmp_path: Path) -> None:
    """Reject documents that cannot prove any progress instead of guessing."""
    for role, document in role_documents(now=_NOW, ages=_FRESH_AGES).items():
        stripped = _without_progress_stamp(role, document)
        report = _probe_document(role, stripped, tmp_path)
        if report.status != STATUS_UNHEALTHY or report.reason != "state_timestamp_missing":
            pytest.fail(f"{role} malformed progress was accepted: {report.render()}")


def test_first_cycle_after_restart_reports_starting(tmp_path: Path) -> None:
    """Treat retained progress from before this container start as startup."""
    document = monitor_document(observed_at=_NOW - 30.0)
    report = _probe_document("monitor", document, tmp_path, start_epoch=_NOW - 10.0)
    if report.status != STATUS_STARTING or report.reason != "awaiting_first_cycle":
        pytest.fail(f"restart was not reported as awaiting its first cycle: {report.render()}")


def test_worker_degradation_never_asks_for_a_restart(tmp_path: Path) -> None:
    """Keep recoverable worker and dependency failures out of restart decisions."""
    degraded = {
        "monitor": monitor_document(observed_at=_NOW - 30.0, write_fail_streak=2),
        "runner": runner_document(observed_at=_NOW - 5.0, claim_failures=4),
    }
    for role, document in degraded.items():
        report = _probe_document(role, document, tmp_path)
        if report.status != STATUS_DEGRADED or report.exit_code != 0:
            pytest.fail(f"{role} degradation demanded a restart: {report.render()}")
        if report.restart_required is not False:
            pytest.fail(f"{role} degradation set the restart marker: {report.render()}")


def test_idle_runner_and_long_test_stay_healthy(tmp_path: Path) -> None:
    """Keep an idle loop and a legitimate in-flight test healthy."""
    idle = _probe_document("runner", runner_document(observed_at=_NOW - 5.0), tmp_path)
    if idle.status != STATUS_HEALTHY:
        pytest.fail(f"idle runner was not healthy: {idle.render()}")
    in_flight = _probe_document(
        "runner",
        runner_document(observed_at=_NOW - 5.0, phase="running", active_started=_NOW - 3_600.0),
        tmp_path,
        start_epoch=_BOOTED_BEFORE_A_LONG_JOB,
    )
    if in_flight.status != STATUS_HEALTHY:
        pytest.fail(f"a long in-flight test was not healthy: {in_flight.render()}")


def test_wedged_runner_is_unhealthy(tmp_path: Path) -> None:
    """Report a loop that stopped polling and a test that overran its window."""
    wedged = _probe_document(
        "runner",
        runner_document(observed_at=_NOW - 5.0, phase="running", active_started=_NOW - 20_000.0),
        tmp_path,
        start_epoch=_BOOTED_BEFORE_A_LONG_JOB,
    )
    if wedged.status != STATUS_UNHEALTHY or wedged.reason != "runner_job_overrun":
        pytest.fail(f"an overrunning test was not reported as wedged: {wedged.render()}")
    stopped = _probe_document("runner", runner_document(observed_at=_NOW - 600.0), tmp_path)
    if stopped.status != STATUS_UNHEALTHY or stopped.reason != "runner_poll_stale":
        pytest.fail(f"a stopped loop was not reported as stale: {stopped.render()}")
