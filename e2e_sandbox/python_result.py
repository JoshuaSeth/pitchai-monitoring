# Copyright (c) 2026 PitchAI. All rights reserved.
"""Submitted Python test result and bounded diagnostic-file output."""

from __future__ import annotations

import json
import traceback
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType

    from domain_checks.event_bus_delivery import JsonValue

RESULT_PREFIX = "E2E_RESULT_JSON="


def safe_str(value: JsonValue | BaseException, *, max_len: int = 2000) -> str:
    """Return the existing bounded string, including the falsey-value empty case."""
    text = str(value or "")
    return text if len(text) <= max_len else text[:max_len]


def write_text(path: Path, content: str) -> None:
    """Preserve best-effort artifact creation without converting system cancellation."""
    with suppress(Exception):
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(content, encoding="utf-8", errors="replace")


@dataclass(frozen=True)
class RunOutcome:
    """First four positional fields of the existing public run result."""

    status: str
    elapsed_ms: float | None
    error_kind: str | None
    error_message: str | None


@dataclass(frozen=True)
class RunResult(RunOutcome):
    """Original flat eight-field result and deterministic JSON serialization."""

    final_url: str | None
    title: str | None
    artifacts: dict[str, str]
    browser_infra_error: bool

    def to_json(self) -> str:
        """Return the original field names, Unicode handling and sorted keys."""
        return json.dumps({
            "status": self.status, "elapsed_ms": self.elapsed_ms,
            "error_kind": self.error_kind, "error_message": self.error_message,
            "final_url": self.final_url, "title": self.title, "artifacts": self.artifacts,
            "browser_infra_error": self.browser_infra_error,
        }, ensure_ascii=False, sort_keys=True)


@dataclass
class RunFailureBoundary:
    """Capture ordinary submission errors for the existing result/log boundary."""

    error: Exception | None = None
    traceback_text: str = ""

    def __enter__(self) -> Self:
        """Return this boundary for the original ordinary-exception scope."""
        return self

    def __exit__(
        self, _kind: type[BaseException] | None, error: BaseException | None, trace: TracebackType | None,
    ) -> bool:
        """Record ordinary failures; leave cancellation and fatal signals unhandled.

        Returns:
            True only for the Exception cases caught by the original runner.
        """
        if not isinstance(error, Exception):
            return False
        self.error = error
        self.traceback_text = "".join(traceback.format_exception(type(error), error, trace))
        return True
