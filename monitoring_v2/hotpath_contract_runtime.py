# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed dynamic boundary for the sibling hotpath contract package."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, NamedTuple, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from .json_types import JsonInput, JsonObject
    from .web_runtime import Router


class HotpathLane(NamedTuple):
    """Canonical identity and target fields for one monitored lane."""

    reminder_id: str
    primary_domain: str
    target_surface: str
    expected_behavior: str
    agent_global_id: str
    lane_id: str
    project: str
    name: str


class HotpathInventory(NamedTuple):
    """Versioned set of canonical lanes and freshness policy."""

    lanes: tuple[HotpathLane, ...]
    incident_cooldown_seconds: int
    stale_after_seconds: int
    expected_interval_seconds: int
    canonical_tag: str
    reviewed_at: str
    schema_version: int


class HotpathReport(Protocol):
    """Validated report fields consumed by monitoring tests and storage."""

    @property
    def lane_id(self) -> str:
        """Return the bound lane identifier."""
        raise NotImplementedError

    @property
    def evidence_uri(self) -> str:
        """Return the private evidence receipt URI."""
        raise NotImplementedError

    def canonical_payload(self) -> JsonObject:
        """Return the immutable strict-JSON identity payload."""
        raise NotImplementedError

    def model_copy(
        self,
        *,
        update: Mapping[str, JsonInput | datetime],
    ) -> HotpathReport:
        """Return a validated-shape copy with selected test fields changed."""
        raise NotImplementedError


class ReportModelClass(Protocol):
    """Pydantic-style report validation class boundary."""

    def model_validate(self, payload: JsonObject) -> HotpathReport:
        """Validate one strict report payload."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class HotpathApplication(Protocol):
    """Host application surface required by hotpath route installation."""

    def include_router(self, router_value: Router) -> None:
        """Attach one hotpath route collection."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class _HotpathTypesModule(Protocol):
    SYNTHETIC_LANE_ID: str
    SYNTHETIC_NAME: str
    SYNTHETIC_PROJECT: str
    SYNTHETIC_TARGET: str
    HotpathReportRequest: ReportModelClass

    def load_inventory(self, path: str) -> HotpathInventory:
        """Load and validate the versioned lane inventory."""
        raise NotImplementedError

    def validate_report_identity(
        self,
        report: HotpathReport,
        inventory: HotpathInventory,
    ) -> HotpathLane | None:
        """Bind a validated report to its exact real lane."""
        raise NotImplementedError


class _HotpathInstallerModule(Protocol):
    def install_hotpath_monitoring(self, application: HotpathApplication) -> None:
        """Install authenticated hotpath routes on the host application."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


HOTPATH_TYPES = cast(
    "_HotpathTypesModule",
    cast("object", import_module("e2e_registry.hotpath_types")),
)
HOTPATH_INSTALLER = cast(
    "_HotpathInstallerModule",
    cast("object", import_module("e2e_registry.hotpath_install")),
)
HOTPATH_REPORT_MODEL = HOTPATH_TYPES.HotpathReportRequest
