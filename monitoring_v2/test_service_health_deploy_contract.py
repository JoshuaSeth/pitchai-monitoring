# Copyright (c) 2026 PitchAI. All rights reserved.
"""Keep the deployed monitoring health contract wired, bounded, and observable."""

from __future__ import annotations

import io
import json
import runpy
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, NamedTuple
from unittest import mock

from .json_types import json_object
from .service_health_evidence import container_start_epoch
from .service_health_roles import SUPPORTED_ROLES, role_spec
from .testing_runtime import pytest

if TYPE_CHECKING:
    from .json_types import JsonObject


class _HealthRun(NamedTuple):
    """One executed deployed health command."""

    exit_code: int
    stdout: str
    stderr: str


_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = _ROOT / ".github" / "workflows" / "ci-cd.yaml"
_WATCHDOG_PATH = _ROOT / "ops" / "run-service-monitoring.sh"
_WATCHDOG_STALE_MARKER: Final = "MONITOR_STALE_AFTER_SECONDS:-"
_HEALTH_MODULE: Final = "monitoring_v2.service_health"
_EXPECTED_SERVICES = frozenset(
    {
        "service-monitoring",
        "e2e-registry",
        "e2e-runner",
        "database-dependency-monitor",
        "scheduler-placement-observer",
        "domain-incident-events",
    },
)
_DEPLOYED_ROLES = (
    ("REGISTRY_NAME", "registry"),
    ("RUNNER_NAME", "runner"),
    ("APP_NAME", "monitor"),
    ("DB_MONITOR_NAME", "database-dependency"),
)
_CLI_STALE_SECONDS = 5
_EXIT_USAGE = 2


def _workflow_text() -> str:
    """Return the raw deployment workflow for exact contract assertions."""
    return _WORKFLOW_PATH.read_text(encoding="utf-8")


def _monitor_state(*, observed_at: float) -> JsonObject:
    """Return one retained monitor cycle document at the requested age."""
    return json_object(
        {
            "version": 6,
            "updated_at": datetime.fromtimestamp(observed_at, tz=UTC).isoformat(),
            "meta": {"state_write_fail_streak": 0},
            "browser_degraded_active": False,
        },
    )


def _run_health_cli(*arguments: str) -> _HealthRun:
    """Return the exit code and streams of one deployed health command run."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    argv = [_HEALTH_MODULE, *arguments]
    with (
        redirect_stdout(stdout),
        redirect_stderr(stderr),
        mock.patch.object(sys, "argv", argv),
        pytest.raises(SystemExit) as exit_signal,
    ):
        _ = runpy.run_module(_HEALTH_MODULE, run_name="__main__")
    code = exit_signal.value.code
    return _HealthRun(
        exit_code=code if isinstance(code, int) else 0,
        stdout=stdout.getvalue(),
        stderr=stderr.getvalue(),
    )


def test_every_deployed_service_has_a_role_contract() -> None:
    """Cover all six monitoring containers, not only the four staged today."""
    services = frozenset(role_spec(role).service for role in SUPPORTED_ROLES)
    if services != _EXPECTED_SERVICES:
        pytest.fail(f"role coverage changed: {sorted(services)}")
    for role in SUPPORTED_ROLES:
        spec = role_spec(role)
        if not spec.evidence_env or not spec.evidence_default or not spec.missing_reason:
            pytest.fail(f"{role} lost its evidence contract")
        if spec.budget.grace_seconds <= 0:
            pytest.fail(f"{role} lost its bounded startup grace")
        if role != "registry" and (spec.extract is None or spec.budget.stale_seconds <= 0):
            pytest.fail(f"{role} lost its progress contract")
    if role_spec("registry").extract is not None:
        pytest.fail("registry must stay on its read-only liveness contract")


def test_deploy_attaches_and_enforces_the_health_contract() -> None:
    """Require the deploy smoke to attach and then prove each health contract."""
    workflow = _workflow_text()
    assert_health_index = workflow.index("assert_health_contract() {")
    for name, role in _DEPLOYED_ROLES:
        command = f'--health-cmd "python -m monitoring_v2.service_health --role {role}"'
        if command not in workflow:
            pytest.fail(f"{name} lost its {role} health command")
        invocation = f'assert_health_contract "${name}" "{role}"'
        if invocation not in workflow:
            pytest.fail(f"deploy smoke never asserts {invocation}")
        if workflow.index(invocation) < assert_health_index:
            pytest.fail(f"{name} health assertion runs before the smoke helper exists")
    for required in (
        "--health-start-period 120s",
        "--health-start-period 300s",
        "--health-start-period 600s",
        "seq 1 30",
        '"$status" == "missing"',
        '"$status" == "unhealthy"',
    ):
        if required not in workflow:
            pytest.fail(f"deploy smoke lost its bounded contract: {required}")


def test_runner_container_publishes_its_heartbeat_contract() -> None:
    """Keep the runner heartbeat path, mount and entrypoint in agreement."""
    workflow = _workflow_text()
    heartbeat_path = role_spec("runner").evidence_default
    for required in (
        "--tmpfs /run/pitchai-health:rw,noexec,nosuid,size=1m",
        f'-e E2E_RUNNER_HEARTBEAT_PATH="{heartbeat_path}"',
        "python -m e2e_runner.health_main",
    ):
        if required not in workflow:
            pytest.fail(f"runner container lost its heartbeat wiring: {required}")
    if "python -m e2e_runner.main" in workflow:
        pytest.fail("runner container bypasses the heartbeat entrypoint")


def test_monitor_health_threshold_follows_the_watchdog_contract() -> None:
    """Keep the health staleness window equal to the bounded recovery contract."""
    watchdog = _WATCHDOG_PATH.read_text(encoding="utf-8")
    marker = watchdog.partition(_WATCHDOG_STALE_MARKER)[2]
    configured_default = int(marker.partition("}")[0])
    if configured_default != role_spec("monitor").budget.stale_seconds:
        pytest.fail("monitor health staleness and the watchdog no longer agree")
    for required in ("exit 75", "completed-cycle state is stale"):
        if required not in watchdog:
            pytest.fail(f"monitor watchdog lost bounded recovery: {required}")


def test_health_command_reports_fresh_and_stale_states_end_to_end(tmp_path: Path) -> None:
    """Prove the deployed command's exit codes for fresh and stale evidence."""
    evidence = tmp_path / "state.json"
    now = time.time()
    _ = evidence.write_text(json.dumps(_monitor_state(observed_at=now - 1.0)), encoding="utf-8")
    healthy = _run_health_cli("--role", "monitor", "--evidence", str(evidence), "--stale-seconds", "600")
    if healthy.exit_code != 0 or "status=healthy" not in healthy.stdout:
        pytest.fail(f"healthy evidence was not reported: {healthy.stdout} {healthy.stderr}")
    stale_stamp = _stale_stamp(now)
    _ = evidence.write_text(json.dumps(_monitor_state(observed_at=stale_stamp)), encoding="utf-8")
    stale = _run_health_cli(
        "--role",
        "monitor",
        "--evidence",
        str(evidence),
        "--stale-seconds",
        str(_CLI_STALE_SECONDS),
    )
    if stale.exit_code != 1 or "reason=monitor_progress_stale" not in stale.stdout:
        pytest.fail(f"stale evidence was not reported: {stale.stdout} {stale.stderr}")
    usage = _run_health_cli("--role", "unsupported-role")
    if usage.exit_code != _EXIT_USAGE or "reason=usage_error" not in usage.stderr:
        pytest.fail(f"unusable invocation was not reported: {usage.stdout} {usage.stderr}")


def _stale_stamp(now: float) -> float:
    """Return a stale stamp that is still newer than this container's start.

    The deployed command reads the container start from procfs, so a stamp must
    be older than the stale window while remaining after the container start.
    """
    start_epoch = container_start_epoch(
        now=now,
        uptime_text=Path("/proc/uptime").read_text(encoding="utf-8"),
        pid_one_stat_text=Path("/proc/1/stat").read_text(encoding="utf-8"),
    )
    stamp = now - float(_CLI_STALE_SECONDS) - 1.0
    if start_epoch is not None and start_epoch >= stamp:
        pytest.skip("container start is newer than the stale fixture stamp")
    return stamp
