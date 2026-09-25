# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock child cleanup guarantees at the guardian process boundary."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from auth_reset_guardian.guardian import CommandNotifier, NotificationError
from auth_reset_guardian.process_boundary import run_process
from auth_reset_guardian.process_types import ProcessOptions
from domain_checks.testing import verify

PROCESS_STATE_FIELD_INDEX = 2
PROCESS_EXIT_WAIT_SECONDS = 2.0
PROCESS_EXIT_POLL_SECONDS = 0.01


def test_process_boundary_reaps_child_after_unexpected_read_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reap the child even when stream collection fails unexpectedly."""
    pid_path = tmp_path / "failed-reader-child.pid"
    child_code = (
        "import os, pathlib, time\n"
        f"pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid()))\n"
        "print('ready', flush=True)\n"
        "time.sleep(30)\n"
    )

    def fail_read(_file_descriptor: int, _amount: int) -> bytes:
        msg = "injected stream read failure"
        raise RuntimeError(msg)

    monkeypatch.setattr("auth_reset_guardian.process_monitor.os.read", fail_read)
    with pytest.raises(RuntimeError, match="injected stream read failure"):
        _ = run_process(
            [sys.executable, "-c", child_code],
            ProcessOptions(
                env={"LANG": "C.UTF-8", "PATH": os.defpath},
                timeout_seconds=2,
                capture_limit=1024,
            ),
        )
    child_pid = int(pid_path.read_text(encoding="utf-8"))
    with pytest.raises(ChildProcessError):
        _ = os.waitpid(child_pid, os.WNOHANG)


def test_process_boundary_terminates_descendants_on_timeout(tmp_path: Path) -> None:
    """Terminate a descendant that inherits the child process-group streams."""
    descendant_pid_path = tmp_path / "descendant.pid"
    child_code = (
        "import os, pathlib, time\n"
        "descendant = os.fork()\n"
        "if descendant == 0:\n"
        f"    pathlib.Path({str(descendant_pid_path)!r}).write_text(str(os.getpid()))\n"
        "    time.sleep(30)\n"
        "    os._exit(0)\n"
        "time.sleep(30)\n"
    )
    with pytest.raises(NotificationError) as captured:
        CommandNotifier(
            [sys.executable, "-c", child_code],
            timeout_seconds=0.5,
            require_private_receipt=False,
        ).notify("terminate descendants")
    verify(captured.value.error_code == "timeout")
    descendant_pid = int(descendant_pid_path.read_text(encoding="utf-8"))
    wait_deadline = time.monotonic() + PROCESS_EXIT_WAIT_SECONDS
    while _process_is_running(descendant_pid) and time.monotonic() < wait_deadline:
        time.sleep(PROCESS_EXIT_POLL_SECONDS)
    verify(not _process_is_running(descendant_pid))


def _process_is_running(pid: int) -> bool:
    """Report whether a Linux process exists in a non-zombie state.

    Returns:
        Whether the process remains live.

    """
    process_stat = Path("/proc") / str(pid) / "stat"
    try:
        stat_fields = process_stat.read_text(encoding="utf-8").split()
    except (FileNotFoundError, ProcessLookupError):
        return False
    return (
        len(stat_fields) > PROCESS_STATE_FIELD_INDEX
        and stat_fields[PROCESS_STATE_FIELD_INDEX] != "Z"
    )
