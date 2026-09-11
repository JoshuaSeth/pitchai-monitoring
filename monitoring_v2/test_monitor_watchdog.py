# Copyright (c) 2026 PitchAI. All rights reserved.
"""Keep stalled monitoring cycles behind a bounded container watchdog."""

from __future__ import annotations

import stat
from pathlib import Path

from .testing_runtime import pytest

_ROOT = Path(__file__).resolve().parents[1]
_WATCHDOG_PATH = _ROOT / "ops" / "run-service-monitoring.sh"
_DOCKERFILE_PATH = _ROOT / "Dockerfile"
_REQUIRED_WATCHDOG_CONTRACT = (
    "MONITOR_STALE_AFTER_SECONDS:-600",
    'state_mtime=$(stat -c %Y "$state_path"',
    'kill -TERM "$target_pid"',
    'kill -KILL "$target_pid"',
    "exit 75",
)
_REQUIRED_BUILD_PROOF = (
    "MONITOR_STALE_AFTER_SECONDS=1",
    'test "$watchdog_status" -eq 75',
    'grep -Fq "completed-cycle state is stale"',
)


def test_watchdog_keeps_stalled_cycle_recovery_bounded() -> None:
    """Require stale-state detection, graceful shutdown, and restart signaling."""
    watchdog_source = _WATCHDOG_PATH.read_text(encoding="utf-8")
    missing_contract = [contract for contract in _REQUIRED_WATCHDOG_CONTRACT if contract not in watchdog_source]

    if missing_contract:
        pytest.fail("service-monitoring watchdog lost its recovery contract")
    if not _WATCHDOG_PATH.stat().st_mode & stat.S_IXUSR:
        pytest.fail("service-monitoring watchdog is not executable")


def test_container_starts_through_the_monitor_watchdog() -> None:
    """Require production's image build and default command to activate supervision."""
    dockerfile = _DOCKERFILE_PATH.read_text(encoding="utf-8")
    expected_command = 'CMD ["/usr/local/bin/run-service-monitoring"]'
    missing_build_proof = [proof for proof in _REQUIRED_BUILD_PROOF if proof not in dockerfile]

    if expected_command not in dockerfile:
        pytest.fail("production container bypasses the service-monitoring watchdog")
    if missing_build_proof:
        pytest.fail("production image build no longer exercises stale-cycle recovery")
