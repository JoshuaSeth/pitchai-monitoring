# Copyright (c) 2026 PitchAI. All rights reserved.
"""Prove each monitoring role publishes actionable and secret-free health reasons."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .json_types import json_object
from .service_health_model import STATUS_DEGRADED, STATUS_HEALTHY
from .service_health_request import parse_request
from .service_health_roles import probe
from .testing_runtime import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from .json_types import JsonObject
    from .service_health_model import HealthReport

_NOW = 1_800_000_000.0
_BOOTED_LONG_AGO = _NOW - 1_000.0
_UNSAFE_CLAIM_DETAIL = "claim failed for https://svc:" + "credential" + "@registry.internal/api"


def _report(role: str, document: JsonObject, tmp_path: Path) -> HealthReport:
    """Return the evaluated report for one role-specific retained document."""
    evidence = tmp_path / f"{role}-progress.json"
    _ = evidence.write_text(json.dumps(document), encoding="utf-8")
    request = parse_request(["--role", role, "--evidence", str(evidence)])
    return probe(request, now=_NOW, start_epoch=_BOOTED_LONG_AGO)


def _runner_heartbeat(*, claim_failures: int, last_claim_error: str | None = None) -> JsonObject:
    """Return one retained runner heartbeat with the requested claim history."""
    return json_object(
        {
            "version": 1,
            "phase": "idle",
            "updated_at_ts": _NOW - 5.0,
            "consecutive_claim_failures": claim_failures,
            "last_claim_error": last_claim_error,
            "completed_jobs": 2,
        },
    )


def _collector_snapshot(*, collector_status: str, error_class: str | None, dependency_status: str) -> JsonObject:
    """Return one retained database dependency snapshot."""
    return json_object(
        {
            "version": 2,
            "status": dependency_status,
            "generated_at_ts": _NOW - 30.0,
            "collector": {
                "status": collector_status,
                "error_class": error_class,
                "observed_at_ts": _NOW - 30.0,
                "last_successful_cycle_at_ts": _NOW - 60.0,
            },
            "dependencies": [{"status": "down"}, {"status": "up"}],
        },
    )


def _observer_snapshot(*, successful_poll: float | None, last_error: str | None) -> JsonObject:
    """Return one retained scheduler placement observer checkpoint."""
    return json_object(
        {
            "version": 1,
            "bootstrapped": True,
            "updated_at_ts": _NOW - 5.0,
            "last_successful_poll_at_ts": successful_poll,
            "last_error": last_error,
            "cells": {},
        },
    )


def _producer_snapshot(*, last_error: str | None, pending: int, open_incidents: int) -> JsonObject:
    """Return one retained domain incident producer checkpoint."""
    return json_object(
        {
            "version": 1,
            "producer": {
                "status": "healthy" if last_error is None else "degraded",
                "bootstrapped": True,
                "updated_at_ts": _NOW - 5.0,
                "pending_count": pending,
                "open_incident_count": open_incidents,
                "last_error": last_error,
            },
        },
    )


def test_runner_claim_failures_publish_a_narrow_classifier(tmp_path: Path) -> None:
    """Degrade a runner whose claims keep failing without restarting it."""
    named = _report("runner", _runner_heartbeat(claim_failures=3, last_claim_error="ConnectError"), tmp_path)
    if named.status != STATUS_DEGRADED or named.reason != "registry_claim_failing:connecterror":
        pytest.fail(f"runner claim failure lost its classifier: {named.render()}")
    if named.exit_code != 0:
        pytest.fail(f"runner claim failure demanded a restart: {named.render()}")
    secret = _report("runner", _runner_heartbeat(claim_failures=4, last_claim_error=_UNSAFE_CLAIM_DETAIL), tmp_path)
    if secret.reason != "registry_claim_failing:unclassified":
        pytest.fail(f"free-form claim failure was published: {secret.render()}")
    if "credential" in secret.render() or "registry.internal" in secret.render():
        pytest.fail("runner health report leaked retained claim detail")


def test_runner_recovers_when_claims_succeed_again(tmp_path: Path) -> None:
    """Return a recovered runner to healthy once claims succeed again."""
    recovered = _report("runner", _runner_heartbeat(claim_failures=0, last_claim_error=None), tmp_path)
    if recovered.status != STATUS_HEALTHY or recovered.exit_code != 0:
        pytest.fail(f"recovered runner was not healthy: {recovered.render()}")


def test_collector_and_dependency_failures_stay_degraded(tmp_path: Path) -> None:
    """Keep collector and monitored-database failures out of restart decisions."""
    collector = _report(
        "database-dependency",
        _collector_snapshot(collector_status="failed", error_class="OperationalError", dependency_status="ok"),
        tmp_path,
    )
    if collector.status != STATUS_DEGRADED or collector.reason != "collector_cycle_failed:operationalerror":
        pytest.fail(f"collector failure lost its classifier: {collector.render()}")
    if collector.exit_code != 0:
        pytest.fail(f"collector failure demanded a restart: {collector.render()}")
    dependency = _report(
        "database-dependency",
        _collector_snapshot(collector_status="healthy", error_class=None, dependency_status="down"),
        tmp_path,
    )
    if dependency.status != STATUS_DEGRADED or dependency.reason != "dependency_unhealthy:down":
        pytest.fail(f"monitored dependency failure was not degraded: {dependency.render()}")
    for token in ("dependencies=2", "dependencies_down=1"):
        if token not in dependency.render():
            pytest.fail(f"dependency detail lost {token}: {dependency.render()}")


def test_collector_rejects_unsupported_state_version(tmp_path: Path) -> None:
    """Reject an unreadable collector contract instead of guessing health."""
    unsupported = _collector_snapshot(collector_status="healthy", error_class=None, dependency_status="ok")
    unsupported["version"] = 1
    with pytest.raises(ValueError, match="unsupported database dependency state version"):
        _ = _report("database-dependency", unsupported, tmp_path)
    malformed = _collector_snapshot(collector_status="healthy", error_class=None, dependency_status="ok")
    malformed["version"] = "2"
    with pytest.raises(ValueError, match="unsupported database dependency state version"):
        _ = _report("database-dependency", malformed, tmp_path)


def test_observer_reports_central_feed_and_cycle_failures(tmp_path: Path) -> None:
    """Degrade the observer for central-feed staleness and cycle failures."""
    fresh = _report("scheduler-observer", _observer_snapshot(successful_poll=_NOW - 30.0, last_error=None), tmp_path)
    if fresh.status != STATUS_HEALTHY:
        pytest.fail(f"observer with a fresh central poll was not healthy: {fresh.render()}")
    stale = _report("scheduler-observer", _observer_snapshot(successful_poll=_NOW - 1_000.0, last_error=None), tmp_path)
    if stale.status != STATUS_DEGRADED or stale.reason != "central_poll_stale":
        pytest.fail(f"observer central feed staleness was not degraded: {stale.render()}")
    failed = _report(
        "scheduler-observer",
        _observer_snapshot(successful_poll=_NOW - 30.0, last_error="cycle_failure:RuntimeError"),
        tmp_path,
    )
    if failed.status != STATUS_DEGRADED or failed.reason != "cycle_error:runtimeerror":
        pytest.fail(f"observer cycle failure lost its classifier: {failed.render()}")


def test_domain_incident_reports_backlog_and_recovery(tmp_path: Path) -> None:
    """Publish producer backlog detail, degrade on errors, and recover cleanly."""
    backlog = _report("domain-incident", _producer_snapshot(last_error=None, pending=3, open_incidents=2), tmp_path)
    if backlog.status != STATUS_HEALTHY:
        pytest.fail(f"producer backlog was not reported healthy: {backlog.render()}")
    for token in ("pending_outbox=3", "open_incidents=2"):
        if token not in backlog.render():
            pytest.fail(f"producer detail lost {token}: {backlog.render()}")
    failing = _report(
        "domain-incident",
        _producer_snapshot(last_error="event_bus_delivery:timeout", pending=0, open_incidents=0),
        tmp_path,
    )
    if failing.status != STATUS_DEGRADED or failing.reason != "cycle_error:timeout":
        pytest.fail(f"producer delivery failure was not degraded: {failing.render()}")
    recovered = _report("domain-incident", _producer_snapshot(last_error=None, pending=0, open_incidents=0), tmp_path)
    if recovered.status != STATUS_HEALTHY:
        pytest.fail(f"recovered producer was not healthy: {recovered.render()}")
