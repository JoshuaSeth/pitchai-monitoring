# Copyright (c) 2026 PitchAI. All rights reserved.
"""Define typed results and failures for reviewed child processes."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Mapping


class ProcessTimeoutError(TimeoutError):
    """A child process exceeded its explicit execution deadline."""


class ProcessOutputLimitError(RuntimeError):
    """A child process exceeded its bounded output allowance."""


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """Represent one completed child process without exposing platform status."""

    returncode: int
    stdout: str
    stderr: str


class ProcessOptions(NamedTuple):
    """Bundle explicit child-process limits and environment isolation."""

    env: Mapping[str, str]
    timeout_seconds: float
    capture_limit: int


type ProcessRunner = Callable[[Sequence[str], ProcessOptions], ProcessResult]
