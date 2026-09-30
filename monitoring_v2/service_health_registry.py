# Copyright (c) 2026 PitchAI. All rights reserved.
"""Safe liveness and read-only usability evidence for the E2E registry."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from .json_types import bool_value, json_object
from .service_health_evidence import age_seconds
from .service_health_liveness import fetch_liveness
from .service_health_model import (
    STATUS_DEGRADED,
    STATUS_HEALTHY,
    STATUS_UNHEALTHY,
    HealthReport,
)
from .service_health_state import startup_report

if TYPE_CHECKING:
    from pathlib import Path

    from .json_types import JsonInput, JsonObject
    from .service_health_request import HealthProbeRequest
    from .service_health_state import ProgressContext

_DB_TIMEOUT_SECONDS: float = 5.0
_MISSING_REASON: str = "registry_database_missing"
_HTTP_OK: int = 200
_EMPTY_INVENTORY: int = 0


@dataclass(frozen=True)
class RegistryUsage:
    """Read-only usability evidence collected from the registry database.

    Attributes:
        tests: Number of registered tests.
        enabled_tests: Number of registered tests that are enabled.
        latest_run_age_seconds: Age of the newest finished run, or ``None``
            when the registry has not finished a run yet.
    """

    tests: int
    enabled_tests: int
    latest_run_age_seconds: float | None


def registry_report(*, request: HealthProbeRequest, context: ProgressContext) -> HealthReport:
    """Return the registry liveness and read-only usability report.

    Args:
        request: Resolved role, database path and liveness URL.
        context: Times, thresholds and instance age for this evaluation.

    Returns:
        The registry report, never ``healthy`` while the liveness endpoint or
        the read-only usability probe fails.
    """
    detail = (f"state_path={request.evidence_path}",)
    if not request.evidence_path.exists():
        return startup_report(
            role=request.role,
            service=request.service,
            reason=_MISSING_REASON,
            detail=detail,
            context=context,
        )
    status_code, body = _liveness_response(request.probe_url)
    liveness_detail = (*detail, f"registry_http_status={status_code}")
    if status_code != _HTTP_OK:
        return HealthReport(
            role=request.role,
            service=request.service,
            status=STATUS_UNHEALTHY,
            reason="registry_http_status",
            detail=liveness_detail,
        )
    if bool_value(body.get("ok")) is not True:
        return HealthReport(
            role=request.role,
            service=request.service,
            status=STATUS_UNHEALTHY,
            reason="registry_http_not_ok",
            detail=liveness_detail,
        )
    usage = _read_only_usage(request.evidence_path)
    usage_detail = (
        *liveness_detail,
        f"registry_tests={usage.tests}",
        f"registry_enabled_tests={usage.enabled_tests}",
        f"registry_latest_run_age_seconds={_age_text(context, usage.latest_run_age_seconds)}",
    )
    if usage.tests == _EMPTY_INVENTORY:
        return HealthReport(
            role=request.role,
            service=request.service,
            status=STATUS_DEGRADED,
            reason="registry_inventory_empty",
            detail=usage_detail,
        )
    return HealthReport(
        role=request.role,
        service=request.service,
        status=STATUS_HEALTHY,
        reason="registry_usable",
        detail=usage_detail,
    )


def _liveness_response(url: str) -> tuple[int, JsonObject]:
    receipt = fetch_liveness(url)
    return receipt.status_code, json_object(cast("JsonInput", json.loads(receipt.text)))


def _read_only_usage(path: Path) -> RegistryUsage:
    # ``mode=ro`` keeps the usability probe from creating or migrating anything.
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=_DB_TIMEOUT_SECONDS)) as connection:
        _require_schema_marker(connection)
        tests = _scalar_int(connection, "SELECT COUNT(*) FROM tests")
        enabled_tests = _scalar_int(connection, "SELECT COUNT(*) FROM tests WHERE enabled=1")
        latest_run_age = _optional_float(connection, "SELECT MAX(finished_at_ts) FROM runs")
    return RegistryUsage(tests=tests, enabled_tests=enabled_tests, latest_run_age_seconds=latest_run_age)


def _require_schema_marker(connection: sqlite3.Connection) -> None:
    query = "SELECT v FROM schema_meta WHERE k='version'"
    row = cast("tuple[object, ...] | None", connection.execute(query).fetchone())
    if row is None:
        message = "registry database has no schema version marker"
        raise ValueError(message)
    version = int(str(row[0]).strip())
    if version < 1:
        message = "registry database schema version is not positive"
        raise ValueError(message)


def _scalar_int(connection: sqlite3.Connection, query: str) -> int:
    row = cast("tuple[object, ...] | None", connection.execute(query).fetchone())
    selected = _EMPTY_INVENTORY if row is None else int(str(row[0]))
    return max(0, selected)


def _optional_float(connection: sqlite3.Connection, query: str) -> float | None:
    row = cast("tuple[object, ...] | None", connection.execute(query).fetchone())
    if row is None or row[0] is None:
        return None
    return float(str(row[0]))


def _age_text(context: ProgressContext, observed: float | None) -> str:
    if observed is None:
        return "none"
    return str(round(age_seconds(context.now, observed)))
