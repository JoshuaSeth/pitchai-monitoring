# Copyright (c) 2026 PitchAI. All rights reserved.
"""Prove the E2E registry health contract is usable and strictly read-only."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from functools import partial
from typing import TYPE_CHECKING, NamedTuple

from httpx import HTTPError

from . import service_health_liveness
from .service_health import unusable_evidence_report
from .service_health_model import STATUS_DEGRADED, STATUS_HEALTHY, STATUS_UNHEALTHY
from .service_health_registry import registry_report
from .service_health_request import HealthProbeRequest, parse_request
from .service_health_roles import role_spec
from .service_health_state import ProgressContext
from .testing_registry import REGISTRY_DATABASE, registry_database, retained_counts, seed_inventory
from .testing_runtime import pytest

if TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType
    from typing import Self

    from .testing_runtime import MonkeyPatch


class _RegistryUnreachableError(HTTPError):
    """Failure the container-local liveness gateway surfaces when it cannot answer."""


class _LivenessResponse(NamedTuple):
    """Minimal liveness response consumed by the registry health probe."""

    status_code: int
    text: str


class _StubLivenessClient:
    """Context-managed liveness client that answers with one canned response."""

    _response: _LivenessResponse

    def __init__(self, *, timeout: float, status_code: int, text: str) -> None:
        _ = timeout
        self._response = _LivenessResponse(status_code=status_code, text=text)

    def __enter__(self) -> Self:
        """Return the canned client as its own context."""
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release nothing; the canned client owns no resources."""

    def get(self, _url: str) -> _LivenessResponse:
        """Return the canned liveness response."""
        return self._response


_NOW = 1_800_000_000.0
_HTTP_OK = 200
_HTTP_UNAVAILABLE = 503
_REGISTRY_TESTS = 2
_REGISTRY_ENABLED_TESTS = 1
_REGISTRY_RUNS = 1
_RUN_AGE_SECONDS = 120.0
_PROBE_URL = "http://127.0.0.1:8111/health"
_UNSAFE_FAILURE_DETAIL = "denied for https://svc:" + "credential" + "@registry.invalid"
_LIVENESS_OK = '{"ok": true}'
_LIVENESS_NOT_OK = '{"ok": false}'


def _registry_request(*, db_path: Path, probe_url: str = _PROBE_URL) -> HealthProbeRequest:
    """Return one resolved registry probe request for an isolated fixture."""
    spec = role_spec("registry")
    return HealthProbeRequest(
        role=spec.role,
        service=spec.service,
        evidence_path=db_path,
        budget=spec.budget,
        probe_url=probe_url,
        missing_reason=spec.missing_reason,
    )


def _role_context(start_epoch: float | None = None) -> ProgressContext:
    """Return the registry progress context used by the deployed container."""
    spec = role_spec("registry")
    return ProgressContext(
        now=_NOW,
        stale_seconds=spec.budget.stale_seconds,
        grace_seconds=spec.budget.grace_seconds,
        extended_seconds=spec.budget.extended_seconds,
        start_epoch=start_epoch,
    )


def _serve_liveness(monkeypatch: MonkeyPatch, response: _LivenessResponse) -> None:
    """Replace the registry liveness client with one canned response."""
    stub = partial(_StubLivenessClient, status_code=response.status_code, text=response.text)
    monkeypatch.setattr(service_health_liveness, "Client", stub)


def test_registry_probe_is_usable_on_the_deployed_schema_and_never_mutates_it(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Report usable inventory while leaving the retained database untouched."""
    db_path = registry_database(tmp_path / "e2e-registry.db")
    seed_inventory(db_path, now=_NOW, run_age_seconds=_RUN_AGE_SECONDS)
    _serve_liveness(monkeypatch, _LivenessResponse(status_code=_HTTP_OK, text=_LIVENESS_OK))
    before_digest = hashlib.sha256(db_path.read_bytes()).hexdigest()
    before_mtime = db_path.stat().st_mtime_ns
    report = registry_report(request=_registry_request(db_path=db_path), context=_role_context())
    version, tests, enabled, runs = retained_counts(db_path)
    if version != REGISTRY_DATABASE.SCHEMA_VERSION:
        pytest.fail("registry health probe fixture drifted from the deployed schema version")
    if (tests, enabled, runs) != (_REGISTRY_TESTS, _REGISTRY_ENABLED_TESTS, _REGISTRY_RUNS):
        pytest.fail("registry health probe created or dropped retained records")
    if report.status != STATUS_HEALTHY or report.reason != "registry_usable":
        pytest.fail(f"usable registry inventory was not healthy: {report.render()}")
    rendered = report.render()
    for token in (f"registry_tests={_REGISTRY_TESTS}", f"registry_latest_run_age_seconds={round(_RUN_AGE_SECONDS)}"):
        if token not in rendered:
            pytest.fail(f"registry evidence lost {token}: {rendered}")
    if (hashlib.sha256(db_path.read_bytes()).hexdigest(), db_path.stat().st_mtime_ns) != (before_digest, before_mtime):
        pytest.fail("registry health probe rewrote the retained database")


def test_registry_probe_reports_empty_inventory_as_degraded(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """Keep an empty registry usable but visibly degraded."""
    db_path = registry_database(tmp_path / "empty-registry.db")
    _serve_liveness(monkeypatch, _LivenessResponse(status_code=_HTTP_OK, text=_LIVENESS_OK))
    report = registry_report(request=_registry_request(db_path=db_path), context=_role_context())
    if report.status != STATUS_DEGRADED or report.reason != "registry_inventory_empty":
        pytest.fail(f"empty registry inventory was not degraded: {report.render()}")
    if report.exit_code != 0:
        pytest.fail(f"empty registry inventory demanded a restart: {report.render()}")


def test_registry_probe_respects_startup_grace_for_an_absent_database(tmp_path: Path) -> None:
    """Report an absent registry database as bounded startup, then unhealthy."""
    request = _registry_request(db_path=tmp_path / "absent-registry.db")
    starting = registry_report(request=request, context=_role_context(_NOW - 1.0))
    if starting.status != "starting" or starting.reason != "registry_database_missing":
        pytest.fail(f"absent registry database was not a bounded startup: {starting.render()}")
    expired = registry_report(request=request, context=_role_context(_NOW - 600.0))
    if expired.status != STATUS_UNHEALTHY:
        pytest.fail(f"absent registry database never expired its grace: {expired.render()}")


def test_registry_probe_rejects_a_degraded_liveness_document(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """Refuse to call a registry healthy while its liveness cannot answer."""
    db_path = registry_database(tmp_path / "e2e-registry.db")
    seed_inventory(db_path, now=_NOW, run_age_seconds=_RUN_AGE_SECONDS)
    for response, expected_reason in (
        (_LivenessResponse(status_code=_HTTP_UNAVAILABLE, text=_LIVENESS_OK), "registry_http_status"),
        (_LivenessResponse(status_code=_HTTP_OK, text=_LIVENESS_NOT_OK), "registry_http_not_ok"),
    ):
        _serve_liveness(monkeypatch, response)
        report = registry_report(request=_registry_request(db_path=db_path), context=_role_context())
        if report.status != STATUS_UNHEALTHY or report.reason != expected_reason:
            pytest.fail(f"degraded liveness was accepted: {report.render()}")


def test_registry_probe_rejects_an_unusable_database(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """Reject a live registry whose configured database has no valid schema."""
    unusable = tmp_path / "unusable-registry.db"
    with closing(sqlite3.connect(str(unusable))) as connection:
        _ = connection.execute("CREATE TABLE unrelated (key TEXT PRIMARY KEY)")
        connection.commit()
    _serve_liveness(monkeypatch, _LivenessResponse(status_code=_HTTP_OK, text=_LIVENESS_OK))
    with pytest.raises(sqlite3.OperationalError):
        _ = registry_report(request=_registry_request(db_path=unusable), context=_role_context())


def test_unusable_registry_evidence_is_classified_without_leaking_detail(tmp_path: Path) -> None:
    """Map registry probe failures onto non-secret operator reason codes."""
    request = _registry_request(db_path=tmp_path / "e2e-registry.db")
    failures: tuple[tuple[BaseException, str], ...] = (
        (_RegistryUnreachableError(_UNSAFE_FAILURE_DETAIL), "registry_unreachable"),
        (sqlite3.OperationalError("no such table"), "registry_database_unusable"),
        (OSError("permission denied"), "registry_liveness_unreadable"),
        (ValueError("malformed schema marker"), "registry_probe_invalid_response"),
    )
    for failure, expected_reason in failures:
        report = unusable_evidence_report(request=request, failure=failure)
        if report.status != STATUS_UNHEALTHY or report.reason != expected_reason:
            pytest.fail(f"registry failure was misclassified: {report.render()}")
        if "credential" in report.render() or "registry.invalid" in report.render():
            pytest.fail("registry health report leaked retained failure detail")


def test_registry_role_resolves_database_and_port_overrides(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """Resolve the deployed registry database and container-local liveness port."""
    db_path = tmp_path / "e2e-registry.db"
    monkeypatch.setenv("E2E_REGISTRY_DB_PATH", str(db_path))
    monkeypatch.setenv("E2E_REGISTRY_PORT", "9999")
    request = parse_request(["--role", "registry"])
    if request.evidence_path != db_path or request.probe_url != "http://127.0.0.1:9999/health":
        pytest.fail(f"registry role resolution changed: {request}")
