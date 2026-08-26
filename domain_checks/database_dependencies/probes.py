# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build, execute, and classify bounded database probe commands."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

from domain_checks.database_dependencies.failure_classification import classify_failure
from domain_checks.database_dependencies.models import ProbeObservation
from domain_checks.database_dependencies.sanitization import sanitized_excerpt
from domain_checks.json_types import bool_value, float_value, json_object, text_value

if TYPE_CHECKING:
    from domain_checks.database_dependencies.docker_gateway import DockerGateway
    from domain_checks.database_dependencies.models import (
        ProbeDefinition,
        ProbeExecution,
    )
    from domain_checks.json_types import JsonValue


class DatabaseProbeProtocolError(RuntimeError):
    """An in-container probe violated its single-line sanitized protocol."""


_TARGET_SOURCE = Path(__file__).with_name("target_probe.txt").read_text(encoding="utf-8")


def _probe_spec(definition: ProbeDefinition, *, timeout_seconds: int) -> str:
    payload = {
        "mode": definition.mode,
        "environment_keys": list(definition.environment_keys),
        "file_environment_keys": list(definition.file_environment_keys),
        "default_credential_path": definition.default_credential_path,
        "default_sqlite_path": definition.default_sqlite_path,
        "engine_attr": definition.engine_attr,
        "engine_callable": definition.engine_callable,
        "sync_driver": definition.sync_driver,
        "relation_checks": list(definition.relation_checks),
        "schema_checks": list(definition.schema_checks),
        "timeout_seconds": timeout_seconds,
    }
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii")


def _failure_observation(
    definition: ProbeDefinition,
    *,
    observed_at_ts: float,
    failure_class: str,
    failure_phase: str,
    excerpt: str,
) -> ProbeObservation:
    return ProbeObservation(
        dependency_id=definition.dependency_id,
        observed_at_ts=observed_at_ts,
        ok=False,
        latency_ms=None,
        failure_class=failure_class,
        failure_phase=failure_phase,
        sqlstate=None,
        sanitized_error_excerpt=excerpt,
    )


def _boundary_observation(
    definition: ProbeDefinition,
    execution: ProbeExecution,
    *,
    observed_at_ts: float,
) -> ProbeObservation | None:
    if execution.boundary_failure is not None:
        return _failure_observation(
            definition,
            observed_at_ts=observed_at_ts,
            failure_class=execution.boundary_failure,
            failure_phase="probe_infrastructure",
            excerpt="The app container could not complete its bounded database probe.",
        )
    if execution.exit_code in {126, 127}:
        return _failure_observation(
            definition,
            observed_at_ts=observed_at_ts,
            failure_class="probe_runtime_missing",
            failure_phase="probe_infrastructure",
            excerpt=sanitized_excerpt(execution.stderr) or "The configured probe runtime is unavailable.",
        )
    if execution.exit_code != 0:
        return _failure_observation(
            definition,
            observed_at_ts=observed_at_ts,
            failure_class="probe_runtime_failure",
            failure_phase="probe_infrastructure",
            excerpt=sanitized_excerpt(execution.stderr) or "The bounded probe process exited unexpectedly.",
        )
    return None


def _protocol_observation(
    definition: ProbeDefinition,
    execution: ProbeExecution,
    *,
    observed_at_ts: float,
) -> ProbeObservation:
    decoded_stdout = execution.stdout.decode("utf-8", errors="strict")
    split_lines = decoded_stdout.splitlines()
    lines = [line for line in split_lines if line.strip()]
    if len(lines) != 1:
        message = "database probe must return exactly one protocol line"
        raise DatabaseProbeProtocolError(message)
    decoded = cast("JsonValue", json.loads(lines[0]))
    payload = json_object(decoded)
    ok = bool_value(payload.get("ok"))
    if ok is None:
        message = "database probe omitted a boolean ok field"
        raise DatabaseProbeProtocolError(message)
    latency = float_value(payload.get("latency_ms"))
    if ok:
        return ProbeObservation(
            dependency_id=definition.dependency_id,
            observed_at_ts=observed_at_ts,
            ok=True,
            latency_ms=latency,
            failure_class=None,
            failure_phase=None,
            sqlstate=None,
            sanitized_error_excerpt=None,
        )
    kind = text_value(payload.get("error_kind"), default="database_error")
    phase = text_value(payload.get("phase"), default="connection")
    sqlstate = text_value(payload.get("sqlstate"))
    excerpt = sanitized_excerpt(payload.get("error_excerpt"))
    return ProbeObservation(
        dependency_id=definition.dependency_id,
        observed_at_ts=observed_at_ts,
        ok=False,
        latency_ms=latency,
        failure_class=classify_failure(kind=kind, phase=phase, sqlstate=sqlstate, excerpt=excerpt),
        failure_phase=phase,
        sqlstate=sqlstate or None,
        sanitized_error_excerpt=excerpt or "Database probe failed without a safe error excerpt.",
    )


def execute_probe(
    gateway: DockerGateway,
    definition: ProbeDefinition,
    *,
    python_executable: str,
    timeout_seconds: int,
    observed_at_ts: float,
) -> ProbeObservation:
    """Execute one definition and return only a sanitized observation.

    Returns:
        One secret-free dependency observation.

    Raises:
        DatabaseProbeProtocolError: If a concrete dependency has no container id.
    """
    if definition.dependency_kind == "coverage_gap":
        return _failure_observation(
            definition,
            observed_at_ts=observed_at_ts,
            failure_class="container_inventory_gap",
            failure_phase="inventory",
            excerpt="No running container matched this required production dependency group.",
        )
    if definition.container_id is None:
        message = "database dependency omitted its concrete container id"
        raise DatabaseProbeProtocolError(message)
    execution = gateway.execute_probe(
        container_id=definition.container_id,
        command=[
            python_executable,
            "-c",
            _TARGET_SOURCE,
            _probe_spec(definition, timeout_seconds=timeout_seconds),
        ],
    )
    boundary = _boundary_observation(definition, execution, observed_at_ts=observed_at_ts)
    if boundary is not None:
        return boundary
    return _protocol_observation(definition, execution, observed_at_ts=observed_at_ts)
