# Copyright (c) 2026 PitchAI. All rights reserved.
"""Subprocess communication boundary for submitted-code execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from e2e_runner.isolation import SandboxIdentity


@dataclass(frozen=True)
class ProcessCapture:
    """Complete subprocess output with explicit deadline state."""

    stdout: bytes
    stderr: bytes
    timed_out: bool
    deadline_seconds: float


def _redact_stream(stream: bytes, sensitive_values: Sequence[str]) -> bytes:
    redacted = stream
    for value in sensitive_values:
        encoded_value = value.encode()
        if encoded_value:
            redacted = redacted.replace(encoded_value, b"[REDACTED]")
    return redacted


async def launch_isolated_process(
    command: list[str],
    *,
    environment: dict[str, str],
    identity: SandboxIdentity,
) -> asyncio.subprocess.Process:
    """Launch a new process session under a leased non-root Unix identity.

    Returns:
        The running isolated subprocess.
    """
    return await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
        user=identity.uid,
        group=identity.gid,
        extra_groups=(),
        umask=identity.umask,
        start_new_session=True,
    )


async def collect_process_output(
    process: asyncio.subprocess.Process,
    *,
    deadline_seconds: float,
    timeout_cleanup: Callable[[], Awaitable[None]],
    sensitive_values: Sequence[str] = (),
) -> ProcessCapture:
    """Collect configured streams and kill a process at its deadline.

    Returns:
        Captured bytes with a declared timeout marker.

    """
    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=deadline_seconds,
        )
    except TimeoutError:
        timed_out = True
        await timeout_cleanup()
        stdout, stderr = await process.communicate()
    return ProcessCapture(
        stdout=_redact_stream(stdout, sensitive_values),
        stderr=_redact_stream(stderr, sensitive_values),
        timed_out=timed_out,
        deadline_seconds=deadline_seconds,
    )
