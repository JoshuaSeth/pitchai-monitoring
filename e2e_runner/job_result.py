# Copyright (c) 2026 PitchAI. All rights reserved.
"""Registry job normalization and the existing completion payload."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NamedTuple, cast

if TYPE_CHECKING:
    from pathlib import Path

    from domain_checks.event_bus_delivery import JsonObject, JsonValue


class JobRequest(NamedTuple):
    """Keep request normalization before the job's ordinary-error boundary."""

    run_id: str
    test_id: str
    tenant_id: str
    base_url: str
    timeout: float
    kind: str
    definition: JsonValue
    source: str | None

    @classmethod
    def parse(cls, job: JsonObject) -> JobRequest:
        """Return the original string/numeric coercions in their evaluation order."""
        run_id = str(job.get("run_id") or "").strip()
        test_id = str(job.get("test_id") or "").strip()
        tenant_id = str(job.get("tenant_id") or "").strip()
        base_url = str(job.get("base_url") or "").strip()
        # Native float rejects malformed container input before reporting completion.
        timeout = float(cast("str | float", job.get("timeout_seconds") or 45.0))
        kind = str(job.get("test_kind") or "stepflow").strip().lower() or "stepflow"
        definition = job.get("definition")
        source = str(job.get("source_relpath") or "").strip() or None
        return cls(run_id, test_id, tenant_id, base_url, timeout, kind, definition, source)


@dataclass
class JobResult:
    """Hold partial job results even when a later operation fails."""

    status: str = "infra_degraded"
    elapsed_ms: JsonValue = None
    error_kind: str | None = None
    error_message: str | None = None
    final_url: JsonValue = None
    title: JsonValue = None
    artifacts: JsonObject = field(default_factory=dict)

    def fail(self, status: str, kind: str, message: str | None) -> None:
        """Update failure classification without erasing earlier measurements/artifacts."""
        self.status = status
        self.error_kind = kind
        self.error_message = message

    def read_parsed(self, parsed: JsonObject) -> None:
        """Consume a submitted result, retaining only string artifact entries."""
        self.status = str(parsed.get("status") or "fail").strip().lower()
        if self.status not in {"pass", "fail", "infra_degraded"}:
            self.status = "fail"
        raw = parsed.get("elapsed_ms")
        self.elapsed_ms = None
        with suppress(Exception):
            self.elapsed_ms = float(cast("str | float", raw)) if raw is not None else None
        self.error_kind = str(parsed.get("error_kind") or "").strip() or None
        self.error_message = str(parsed.get("error_message") or "").strip() or None
        self.final_url = str(parsed.get("final_url") or "").strip() or None
        self.title = str(parsed.get("title") or "").strip() or None
        artifacts = parsed.get("artifacts")
        if isinstance(artifacts, dict):
            for key, value in artifacts.items():
                if isinstance(value, str) and value.strip():
                    self.artifacts[key] = value.strip()

    def write_output(self, directory: Path, output: str) -> None:
        """Best-effort persistence precedes parsing, retaining the existing filename."""
        with suppress(Exception):
            _ = (directory / "runner_output.log").write_text(output + "\n", encoding="utf-8", errors="replace")
            _ = self.artifacts.setdefault("runner_output", "runner_output.log")

    def payload(self, started: float, finished: float) -> JsonObject:
        """Return all nine existing fields, preserving final conversion failures."""
        elapsed = float(cast("str | float", self.elapsed_ms)) if self.elapsed_ms is not None else None
        return {"status": self.status, "elapsed_ms": elapsed, "error_kind": self.error_kind,
                "error_message": self.error_message, "final_url": self.final_url, "title": self.title,
                "artifacts": self.artifacts, "started_at_ts": float(started), "finished_at_ts": float(finished)}
