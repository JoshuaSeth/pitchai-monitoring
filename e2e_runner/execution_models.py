# Copyright (c) 2026 PitchAI. All rights reserved.
"""Input models shared by submitted-code command and execution boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class CodeExecutionRequest:
    """All inputs required to launch one submitted code test."""

    kind: str
    test_file: Path
    base_url: str
    artifacts_dir: Path
    timeout_seconds: float
    trace_on_failure: bool
    trusted_credentials: dict[str, str]
