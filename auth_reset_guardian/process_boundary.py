# Copyright (c) 2026 PitchAI. All rights reserved.
"""Execute reviewed child commands with bounded, shell-free process IO."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .process_monitor import BoundedCapture, capture_process
from .process_spawn import spawn_process
from .process_types import ProcessOutputLimitError, ProcessResult

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .process_types import ProcessOptions


def run_process(
    command: Sequence[str],
    options: ProcessOptions,
) -> ProcessResult:
    """Execute one argv vector and capture bounded stdout and stderr.

    Returns:
        The completed process result.

    Raises:
        ProcessOutputLimitError: If stdout or stderr exceeds the capture limit.
        ValueError: If the execution contract is invalid.

    """
    if not command:
        msg = "process command must not be empty"
        raise ValueError(msg)
    if any(not part for part in command):
        msg = "process command arguments must be non-empty strings"
        raise ValueError(msg)
    if options.timeout_seconds <= 0:
        msg = "process timeout must be positive"
        raise ValueError(msg)
    if options.capture_limit <= 0:
        msg = "process capture limit must be positive"
        raise ValueError(msg)
    stdout = BoundedCapture(options.capture_limit)
    stderr = BoundedCapture(options.capture_limit)
    pid, descriptors = spawn_process(command, options.env)
    status = capture_process(
        pid,
        descriptors,
        stdout=stdout,
        stderr=stderr,
        timeout_seconds=options.timeout_seconds,
    )
    if stdout.exceeded or stderr.exceeded:
        msg = "child process output exceeded its capture limit"
        raise ProcessOutputLimitError(msg)
    return ProcessResult(
        returncode=os.waitstatus_to_exitcode(status),
        stdout=stdout.data.decode("utf-8", errors="replace"),
        stderr=stderr.data.decode("utf-8", errors="replace"),
    )
