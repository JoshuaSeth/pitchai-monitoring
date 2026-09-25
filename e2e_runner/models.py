# Copyright (c) 2026 PitchAI. All rights reserved.
"""Concrete runner contracts shared across worker components."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, NamedTuple

from e2e_registry.models import (
    require_float,
    require_json_object,
    require_text,
)

if TYPE_CHECKING:
    from pathlib import Path

    from e2e_registry.models import JsonObject, JsonValue

type JobStatus = Literal["pass", "fail", "infra_degraded"]


def _optional_text(value: JsonValue, *, label: str) -> str | None:
    if value is None:
        return None
    return require_text(value, label=label).strip()


@dataclass(frozen=True)
class RunnerConfig:
    """Validated process configuration for one runner instance."""

    registry_base_url: str
    runner_token: str
    artifacts_dir: Path
    tests_dir: Path
    poll_seconds: float
    concurrency: int
    trace_on_failure: bool


class RunnerJob(NamedTuple):
    """One claimed registry run ready for execution."""

    run_id: str
    test_id: str
    tenant_id: str
    test_name: str
    base_url: str
    timeout_seconds: float
    test_kind: str
    definition: JsonObject
    source_relpath: str | None
    source_filename: str | None
    source_sha256: str | None

    @classmethod
    def from_json(cls, payload: JsonObject) -> RunnerJob:
        """Validate a claim payload received from the registry.

        Returns:
            A concrete runner job.

        Raises:
            ValueError: If a job field violates the runner contract.
        """
        raw_kind = payload.get("test_kind")
        test_kind = "stepflow" if raw_kind is None else require_text(raw_kind, label="test_kind").strip().lower()
        raw_definition = payload.get("definition")
        definition = {} if raw_definition is None else require_json_object(raw_definition, label="definition")
        raw_timeout = payload.get("timeout_seconds")
        timeout_seconds = 45.0 if raw_timeout is None else require_float(raw_timeout, label="timeout_seconds")
        if timeout_seconds <= 0:
            message = "timeout_seconds must be positive"
            raise ValueError(message)
        return cls(
            run_id=require_text(payload.get("run_id"), label="run_id").strip(),
            test_id=require_text(payload.get("test_id"), label="test_id").strip(),
            tenant_id=require_text(payload.get("tenant_id"), label="tenant_id").strip(),
            test_name=require_text(payload.get("test_name"), label="test_name").strip(),
            base_url=require_text(payload.get("base_url"), label="base_url").strip(),
            timeout_seconds=timeout_seconds,
            test_kind=test_kind,
            definition=definition,
            source_relpath=_optional_text(payload.get("source_relpath"), label="source_relpath"),
            source_filename=_optional_text(payload.get("source_filename"), label="source_filename"),
            source_sha256=_optional_text(payload.get("source_sha256"), label="source_sha256"),
        )


@dataclass(frozen=True)
class JobResult:
    """Normalized result produced by either runner execution backend."""

    status: JobStatus
    elapsed_ms: float | None = None
    error_kind: str | None = None
    error_message: str | None = None
    final_url: str | None = None
    title: str | None = None
    artifacts: JsonObject = field(default_factory=dict)

    @classmethod
    def failure(cls, *, error_kind: str, error_message: str) -> JobResult:
        """Build a deterministic test failure.

        Returns:
            A failed job result.
        """
        return cls(status="fail", error_kind=error_kind, error_message=error_message)

    @classmethod
    def infrastructure_failure(cls, *, error_kind: str, error_message: str) -> JobResult:
        """Build an explicit infrastructure-degraded result.

        Returns:
            An infrastructure-degraded job result.
        """
        return cls(status="infra_degraded", error_kind=error_kind, error_message=error_message)

    @classmethod
    def unexpected_failure(cls, error: BaseException) -> JobResult:
        """Fail closed when execution raises outside its declared error contract.

        Returns:
            A failed result that identifies the runner exception.
        """
        message = str(error).strip() or type(error).__name__
        return cls.failure(
            error_kind="runner_error",
            error_message=f"{type(error).__name__}: {message}"[:2_000],
        )

    def completion_payload(self, *, started_at_ts: float, finished_at_ts: float) -> JsonObject:
        """Build the registry completion payload.

        Returns:
            JSON-compatible completion fields.
        """
        return {
            "status": self.status,
            "elapsed_ms": self.elapsed_ms,
            "error_kind": self.error_kind,
            "error_message": self.error_message,
            "final_url": self.final_url,
            "title": self.title,
            "artifacts": self.artifacts,
            "started_at_ts": started_at_ts,
            "finished_at_ts": finished_at_ts,
        }
