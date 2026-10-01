# Copyright (c) 2026 PitchAI. All rights reserved.
"""Keep the runner heartbeat writable, meaningful, and non-blocking."""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
from importlib import import_module
from typing import TYPE_CHECKING, Final, cast
from unittest import mock

from .health_main import heartbeat_path, heartbeat_seconds, install_instrumentation
from .heartbeat import (
    PHASE_CLAIMING,
    PHASE_IDLE,
    PHASE_RUNNING,
    RunnerHeartbeat,
    narrow_test_id,
    start_heartbeat_publisher,
)
from .testing_runtime import pytest

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence
    from pathlib import Path

    from .heartbeat import HeartbeatDocument, JobValue

_MAIN = import_module("e2e_runner.main")
_NAMESPACE = cast("dict[str, object]", vars(cast("object", _MAIN)))
_PUBLISH_TIMEOUT_SECONDS: Final = 2.0
_POLL_SECONDS: Final = 0.01
_MINIMUM_CADENCE_SECONDS: Final = 1.0
_CONFIGURED_CADENCE_SECONDS: Final = 30.0
_UNUSABLE_CADENCE_SECONDS: Final = 0.1
_MAXIMUM_TEST_ID_LENGTH: Final = 64
_MONITORED_FIELDS: Final = frozenset(
    {
        "version",
        "phase",
        "updated_at_ts",
        "started_at_ts",
        "claim_attempts",
        "claim_successes",
        "consecutive_claim_failures",
        "last_claim_error",
        "completed_jobs",
        "active_job_test_id",
        "active_job_started_ts",
        "last_job_finished_ts",
    },
)

type ClaimCall = Callable[[None, None], Awaitable[Sequence[Mapping[str, JobValue]]]]
type JobCall = Callable[[None, None, None, Mapping[str, JobValue]], Awaitable[None]]


def _heartbeat(tmp_path: Path) -> RunnerHeartbeat:
    """Return one idle heartbeat record backed by an isolated document."""
    return RunnerHeartbeat(path=tmp_path / "heartbeat.json")


def _installed_claim() -> ClaimCall:
    """Return the claim hook currently installed on the runner module."""
    return cast("ClaimCall", _NAMESPACE["_claim_jobs"])


def _installed_job() -> JobCall:
    """Return the job hook currently installed on the runner module."""
    return cast("JobCall", _NAMESPACE["_run_one_job"])


def _document(path: Path) -> HeartbeatDocument:
    """Return the persisted heartbeat document decoded from disk."""
    return cast("HeartbeatDocument", cast("object", json.loads(path.read_text(encoding="utf-8"))))


def _await_file(path: Path) -> None:
    """Wait for the publisher to create the heartbeat document."""
    deadline = time.monotonic() + _PUBLISH_TIMEOUT_SECONDS
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(_POLL_SECONDS)
    if not path.exists():
        pytest.fail("heartbeat publisher never wrote its document")


async def _surfaced_failure[Result](call: Awaitable[Result]) -> BaseException | None:
    """Return the failure one instrumented call surfaced, ``None`` when it returned."""
    task = asyncio.ensure_future(call)
    _ = await asyncio.wait({task})
    return task.exception()


def test_idle_heartbeat_starts_from_a_clean_snapshot(tmp_path: Path) -> None:
    """Publish an idle, versioned record before the loop claims anything."""
    heartbeat = _heartbeat(tmp_path)
    snapshot = heartbeat.snapshot()
    if snapshot["phase"] != PHASE_IDLE or snapshot["completed_jobs"] != 0:
        pytest.fail("fresh heartbeat was not idle and empty")
    if snapshot["updated_at_ts"] != snapshot["started_at_ts"]:
        pytest.fail("fresh heartbeat did not start from one stamp")
    if snapshot["active_job_test_id"] is not None or snapshot["active_job_started_ts"] is not None:
        pytest.fail("idle heartbeat claimed an in-flight test")


def test_claim_and_job_transitions_are_recorded(tmp_path: Path) -> None:
    """Record claiming, running, completion, and narrow claim failures."""
    heartbeat = _heartbeat(tmp_path)
    heartbeat.record_claim_attempt()
    if heartbeat.snapshot()["phase"] != PHASE_CLAIMING:
        pytest.fail("claim attempt did not move the heartbeat into claiming")
    heartbeat.record_claim_error(error_class="TimeoutError")
    failed = heartbeat.snapshot()
    if failed["consecutive_claim_failures"] != 1 or failed["last_claim_error"] != "TimeoutError":
        pytest.fail("claim failure was not retained for the health contract")
    heartbeat.record_claim_success()
    recovered = heartbeat.snapshot()
    if recovered["phase"] != PHASE_IDLE or recovered["last_claim_error"] is not None:
        pytest.fail("successful claim did not clear the failure state")
    if recovered["claim_successes"] != 1 or recovered["consecutive_claim_failures"] != 0:
        pytest.fail("successful claim did not reset the failure streak")
    heartbeat.record_job_start(test_id="smoke.case")
    running = heartbeat.snapshot()
    if running["phase"] != PHASE_RUNNING or running["active_job_test_id"] != "smoke.case":
        pytest.fail("in-flight test was not published")
    heartbeat.record_job_finish()
    finished = heartbeat.snapshot()
    if finished["completed_jobs"] != 1 or finished["active_job_started_ts"] is not None:
        pytest.fail("finished test was not cleared")


def test_heartbeat_write_is_atomic_and_parseable(tmp_path: Path) -> None:
    """Persist one parseable document and leave no temporary file behind."""
    path = tmp_path / "heartbeat.json"
    heartbeat = RunnerHeartbeat(path=path)
    heartbeat.record_job_start(test_id="smoke.case")
    heartbeat.write()
    document = _document(path)
    if document["phase"] != PHASE_RUNNING:
        pytest.fail("persisted heartbeat did not match the live record")
    if (tmp_path / f".{path.name}.tmp").exists():
        pytest.fail("heartbeat write left its temporary file behind")


def test_publisher_keeps_the_document_fresh(tmp_path: Path) -> None:
    """Rewrite the heartbeat repeatedly without touching runner behaviour."""
    path = tmp_path / "heartbeat.json"
    heartbeat = RunnerHeartbeat(path=path)
    _ = start_heartbeat_publisher(heartbeat=heartbeat, interval_seconds=_POLL_SECONDS)
    _await_file(path)
    document = _document(path)
    if document["phase"] != PHASE_IDLE or document["version"] != 1:
        pytest.fail("published heartbeat lost its contract")


async def test_instrumentation_records_the_real_loop_lifecycle(
    tmp_path: Path,
) -> None:
    """Wrap the runner loop so claims, jobs, and completions are observable."""
    heartbeat = _heartbeat(tmp_path)
    observed: list[HeartbeatDocument] = []

    async def fake_claim(_client: None, _config: None) -> list[dict[str, JobValue]]:
        await asyncio.sleep(0)
        return [{"test_id": "smoke.case"}]

    async def fake_job(_browser: None, _config: None, _client: None, _job: Mapping[str, JobValue]) -> None:
        await asyncio.sleep(0)
        observed.append(heartbeat.snapshot())

    with mock.patch.object(_MAIN, "_claim_jobs", fake_claim), mock.patch.object(_MAIN, "_run_one_job", fake_job):
        install_instrumentation(heartbeat)
        claimed = await _installed_claim()(None, None)
        if list(claimed) != [{"test_id": "smoke.case"}]:
            pytest.fail("instrumented claim no longer returns the registry jobs")
        if heartbeat.snapshot()["claim_successes"] != 1:
            pytest.fail("instrumented claim was not recorded")
        await _installed_job()(None, None, None, {"test_id": "smoke.case"})
    if not observed or observed[0]["phase"] != PHASE_RUNNING:
        pytest.fail("in-flight job was not visible to the health contract")
    if observed[0]["active_job_test_id"] != "smoke.case" or heartbeat.snapshot()["completed_jobs"] != 1:
        pytest.fail("job completion was not recorded")


async def test_failing_claim_and_job_are_recorded_and_reraised(
    tmp_path: Path,
) -> None:
    """Retain failure classes while the original error keeps its traceback."""
    heartbeat = _heartbeat(tmp_path)

    async def failing_claim(_client: None, _config: None) -> list[dict[str, JobValue]]:
        await asyncio.sleep(0)
        raise TimeoutError

    async def failing_job(_browser: None, _config: None, _client: None, _job: Mapping[str, JobValue]) -> None:
        await asyncio.sleep(0)
        raise RuntimeError

    with mock.patch.object(_MAIN, "_claim_jobs", failing_claim), mock.patch.object(_MAIN, "_run_one_job", failing_job):
        install_instrumentation(heartbeat)
        claim_failure = await _surfaced_failure(_installed_claim()(None, None))
        if not isinstance(claim_failure, TimeoutError):
            pytest.fail(f"failed claim did not surface its own failure: {claim_failure!r}")
        failed = heartbeat.snapshot()
        if failed["consecutive_claim_failures"] != 1 or failed["last_claim_error"] != "TimeoutError":
            pytest.fail("failed claim was not retained for the health contract")
        job_failure = await _surfaced_failure(_installed_job()(None, None, None, {"test_id": "smoke.case"}))
        if not isinstance(job_failure, RuntimeError):
            pytest.fail(f"failed job did not surface its own failure: {job_failure!r}")
    if heartbeat.snapshot()["completed_jobs"] != 1:
        pytest.fail("failed job did not clear the in-flight test")


def test_heartbeat_identifiers_and_cadence_are_bounded(tmp_path: Path) -> None:
    """Keep published identifiers narrow and the publish cadence bounded."""
    if narrow_test_id("smoke.case") != "smoke.case" or narrow_test_id("bad case"):
        pytest.fail("runner published an unusable test identifier")
    if narrow_test_id("x" * (_MAXIMUM_TEST_ID_LENGTH + 1)):
        pytest.fail("runner published an unbounded test identifier")
    configured = tmp_path / "heartbeat.json"
    overrides = {
        "E2E_RUNNER_HEARTBEAT_PATH": str(configured),
        "E2E_RUNNER_HEARTBEAT_SECONDS": str(_UNUSABLE_CADENCE_SECONDS),
    }
    with mock.patch.dict(os.environ, overrides):
        if heartbeat_path() != configured:
            pytest.fail("runner heartbeat path override was ignored")
        if not math.isclose(heartbeat_seconds(), _MINIMUM_CADENCE_SECONDS):
            pytest.fail("runner heartbeat cadence was not bounded")
    with mock.patch.dict(os.environ, {"E2E_RUNNER_HEARTBEAT_SECONDS": str(_CONFIGURED_CADENCE_SECONDS)}):
        if not math.isclose(heartbeat_seconds(), _CONFIGURED_CADENCE_SECONDS):
            pytest.fail("runner heartbeat cadence override was ignored")


def test_published_document_carries_the_monitored_fields(tmp_path: Path) -> None:
    """Publish exactly the fields the monitoring health contract reads."""
    heartbeat = _heartbeat(tmp_path)
    heartbeat.record_claim_attempt()
    heartbeat.record_job_start(test_id="smoke.case")
    published = frozenset(heartbeat.snapshot())
    if published != _MONITORED_FIELDS:
        pytest.fail(f"runner heartbeat document contract changed: {sorted(published)}")
