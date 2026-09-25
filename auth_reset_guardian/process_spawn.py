# Copyright (c) 2026 PitchAI. All rights reserved.
"""Create shell-free child processes with isolated standard streams."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_STANDARD_INPUT = 0
_STANDARD_OUTPUT = 1
_STANDARD_ERROR = 2


@dataclass(frozen=True, slots=True)
class ProcessReadDescriptors:
    """Own the parent-side descriptors drained after spawning."""

    stdout: int
    stderr: int


@dataclass(frozen=True, slots=True)
class _ProcessPipes:
    """Own the read and write descriptors created for one child."""

    stdout_read: int
    stdout_write: int
    stderr_read: int
    stderr_write: int


def spawn_process(
    command: Sequence[str],
    env: Mapping[str, str],
) -> tuple[int, ProcessReadDescriptors]:
    """Spawn one child and return its pid and nonblocking read descriptors.

    Returns:
        The child pid and parent-side read descriptors.

    Raises:
        OSError: If pipe creation, file opening, or process spawning fails.

    """
    pipes = _open_process_pipes()
    try:
        stdin_fd = os.open(os.devnull, os.O_RDONLY | os.O_CLOEXEC)
    except OSError:
        close_descriptors(_pipe_descriptors(pipes))
        raise
    try:
        pid = _spawn_command(command, env, pipes, stdin_fd=stdin_fd)
    except OSError:
        close_descriptors((*_pipe_descriptors(pipes), stdin_fd))
        raise
    close_descriptors((stdin_fd, pipes.stdout_write, pipes.stderr_write))
    return pid, ProcessReadDescriptors(pipes.stdout_read, pipes.stderr_read)


def close_descriptors(file_descriptors: Sequence[int]) -> None:
    """Close every process descriptor owned by the current branch."""
    for file_descriptor in file_descriptors:
        try:
            os.close(file_descriptor)
        except OSError:
            continue


def _set_nonblocking(file_descriptors: Sequence[int]) -> None:
    """Configure every parent-side read descriptor for nonblocking drains."""
    for file_descriptor in file_descriptors:
        os.set_blocking(file_descriptor, False)


def _open_process_pipes() -> _ProcessPipes:
    """Create blocking child writes and nonblocking parent reads.

    Returns:
        The four owned pipe descriptors.

    Raises:
        OSError: If pipe creation or descriptor configuration fails.

    """
    stdout_read, stdout_write = os.pipe2(os.O_CLOEXEC)
    try:
        stderr_read, stderr_write = os.pipe2(os.O_CLOEXEC)
    except OSError:
        close_descriptors((stdout_read, stdout_write))
        raise
    pipes = _ProcessPipes(stdout_read, stdout_write, stderr_read, stderr_write)
    read_descriptors = (pipes.stdout_read, pipes.stderr_read)
    try:
        _set_nonblocking(read_descriptors)
    except OSError:
        close_descriptors(_pipe_descriptors(pipes))
        raise
    return pipes


def _spawn_command(
    command: Sequence[str],
    env: Mapping[str, str],
    pipes: _ProcessPipes,
    *,
    stdin_fd: int,
) -> int:
    """Spawn an argv vector in a dedicated process group.

    Returns:
        The child process identifier.

    """
    file_actions = (
        (os.POSIX_SPAWN_DUP2, stdin_fd, _STANDARD_INPUT),
        (os.POSIX_SPAWN_DUP2, pipes.stdout_write, _STANDARD_OUTPUT),
        (os.POSIX_SPAWN_DUP2, pipes.stderr_write, _STANDARD_ERROR),
        (os.POSIX_SPAWN_CLOSE, pipes.stdout_read),
        (os.POSIX_SPAWN_CLOSE, pipes.stderr_read),
        (os.POSIX_SPAWN_CLOSE, stdin_fd),
        (os.POSIX_SPAWN_CLOSE, pipes.stdout_write),
        (os.POSIX_SPAWN_CLOSE, pipes.stderr_write),
    )
    argv = tuple(command)
    return os.posix_spawnp(
        argv[0],
        argv,
        dict(env),
        file_actions=file_actions,
        setpgroup=0,
    )


def _pipe_descriptors(pipes: _ProcessPipes) -> tuple[int, int, int, int]:
    """Return every descriptor owned by one process-pipe bundle.

    Returns:
        The complete descriptor tuple.

    """
    return (
        pipes.stdout_read,
        pipes.stdout_write,
        pipes.stderr_read,
        pipes.stderr_write,
    )
