# Copyright (c) 2026 PitchAI. All rights reserved.
"""Concrete data contracts for the Playwright Python sandbox."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal, NamedTuple

if TYPE_CHECKING:
    from pathlib import Path

type SandboxStatus = Literal["pass", "fail", "infra_degraded"]


class SandboxRequest(NamedTuple):
    """Validated command-line request for one submitted Python test."""

    test_file: Path
    base_url: str
    artifacts_dir: Path
    timeout_seconds: float
    trace_on_failure: bool


class RunResult(NamedTuple):
    """Machine-readable outcome returned to the parent E2E runner."""

    status: SandboxStatus
    elapsed_ms: float | None
    error_kind: str | None
    error_message: str | None
    final_url: str | None
    title: str | None
    artifacts: dict[str, str]
    browser_infra_error: bool

    def to_json(self) -> str:
        """Serialize this result for the runner protocol.

        Returns:
            Deterministic JSON text.
        """
        return json.dumps(
            {
                "browser_infra_error": self.browser_infra_error,
                "status": self.status,
                "artifacts": self.artifacts,
                "title": self.title,
                "final_url": self.final_url,
                "elapsed_ms": self.elapsed_ms,
                "error_message": self.error_message,
                "error_kind": self.error_kind,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
