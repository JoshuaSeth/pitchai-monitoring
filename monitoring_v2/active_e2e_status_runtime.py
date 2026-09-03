# Copyright (c) 2026 PitchAI. All rights reserved.
"""Project and install active-only status at the legacy registry boundary."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

from .json_types import int_value, json_object, normalize_json, object_list

if TYPE_CHECKING:
    from .json_types import JsonInput, JsonObject
    from .registry_runtime import RegistrySettings


@dataclass(frozen=True)
class E2ETestStatusProjection:
    """Active, disabled, and failing test counts for one status surface."""

    active: int
    disabled: int
    failing: int


def project_e2e_test_status(records: JsonInput) -> E2ETestStatusProjection:
    """Count only enabled tests as active or failing.

    Returns:
        Reconciled status counts. Missing ``enabled`` values retain the legacy
        enabled default, while malformed or explicit non-one values fail closed
        as disabled.
    """
    active = 0
    disabled = 0
    failing = 0
    for record in object_list(records):
        raw_enabled = record.get("enabled")
        enabled = raw_enabled is None or int_value(raw_enabled) == 1
        if not enabled:
            disabled += 1
            continue
        active += 1
        if int_value(record.get("effective_ok")) == 0:
            failing += 1
    return E2ETestStatusProjection(active=active, disabled=disabled, failing=failing)


def reconcile_e2e_status_summary(summary: JsonInput) -> JsonObject:
    """Remove disabled rows from alert-facing status while retaining their count.

    Returns:
        A copied status document whose totals and visible rows describe only
        runnable tests. Enabled failures remain visible and alertable.
    """
    reconciled = json_object(summary)
    tests = object_list(reconciled.get("tests"))
    active_tests: list[JsonObject] = []
    for test in tests:
        raw_enabled = test.get("enabled")
        if raw_enabled is None or int_value(raw_enabled) == 1:
            active_tests.append(test)
    projection = project_e2e_test_status(tests)
    reconciled["tests"] = normalize_json(active_tests)
    reconciled["total_tests"] = projection.active
    reconciled["disabled_tests"] = projection.disabled
    reconciled["failing_tests"] = projection.failing
    return reconciled


class StatusSummaryBuilder(Protocol):
    """Callable contract for the legacy registry status query."""

    def __call__(self, settings: RegistrySettings) -> JsonObject:
        """Return one registry status document."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the adapter contract name."""
        raise NotImplementedError


class RegistryDatabase(Protocol):
    """Mutable legacy database surface used by the runtime installer."""

    status_summary: object

    def contract_name(self) -> str:
        """Return the adapter contract name."""
        raise NotImplementedError

    def supports_status_summary_replacement(self) -> bool:
        """Report support for replacing the status query."""
        raise NotImplementedError


_DATABASE = cast("RegistryDatabase", cast("object", import_module("e2e_registry.db")))
_LEGACY_STATUS_SUMMARY = cast("StatusSummaryBuilder", _DATABASE.status_summary)


def active_status_summary(settings: RegistrySettings) -> JsonObject:
    """Return alert-facing status containing only runnable tests.

    Returns:
        Reconciled status with disabled historical rows excluded.
    """
    legacy_summary = _LEGACY_STATUS_SUMMARY(settings)
    return reconcile_e2e_status_summary(legacy_summary)


def install_active_status_projection() -> None:
    """Install active-test semantics for every production status consumer."""
    if _DATABASE.status_summary is active_status_summary:
        return
    _DATABASE.status_summary = active_status_summary
