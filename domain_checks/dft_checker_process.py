# Copyright (c) 2026 PitchAI. All rights reserved.
"""Bounded local invocation of the producer-owned, read-only status checker."""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from typing import TYPE_CHECKING

from .dft_retention_consumer import CheckerObservation, checker_observation

if TYPE_CHECKING:
    from pathlib import Path

_MAX_RESPONSE_BYTES = 32_768
_TIMEOUT_SECONDS = 10


async def observe_checker(source_root: Path, allocated_config: Path) -> CheckerObservation:
    """Execute the published checker only in its admitted local namespace.

    Admission must supply the reviewed source directory, private configuration,
    host clock capability and same host/boot as expiry. This helper does not
    create a mount, executor, service or remote connection. Standard error is
    discarded; arbitrary command output cannot enter events or logs.

    Returns:
        Content-free failure for a timeout, unavailable process or bad output.
    """
    if os.geteuid() != 0 or not source_root.is_absolute() or not allocated_config.is_absolute():
        return CheckerObservation(errors=("checker_namespace_unavailable",))
    process: asyncio.subprocess.Process | None = None
    with suppress(OSError):
        process = await asyncio.create_subprocess_exec(
            "/usr/bin/python3", "-m", "scripts.dft_access_log_status", "--config", str(allocated_config),
            cwd=source_root, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=_MAX_RESPONSE_BYTES + 1,
        )
    if process is None:
        return CheckerObservation(errors=("checker_unavailable",))
    try:
        return await _read_process(process)
    finally:
        if process.returncode is None:
            process.kill()
        await process.communicate()


async def _read_process(process: asyncio.subprocess.Process) -> CheckerObservation:
    observation = CheckerObservation(errors=("checker_unavailable",))
    with suppress(OSError):
        observation = await _capture(process)
    return observation


async def _capture(process: asyncio.subprocess.Process) -> CheckerObservation:
    if process.stdout is None:
        return CheckerObservation(errors=("checker_response_missing",))
    async with asyncio.timeout(_TIMEOUT_SECONDS):
        output = bytearray()
        while len(output) <= _MAX_RESPONSE_BYTES:
            chunk = await process.stdout.read(_MAX_RESPONSE_BYTES + 1 - len(output))
            if not chunk:
                break
            output.extend(chunk)
        if len(output) > _MAX_RESPONSE_BYTES:
            return CheckerObservation(errors=("checker_response_oversized",))
        returncode = await process.wait()
    return checker_observation(returncode, bytes(output))
