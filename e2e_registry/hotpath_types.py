# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed contracts for agent-reported client hotpath results."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast

import pydantic

if TYPE_CHECKING:
    from collections.abc import Callable

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
type Severity = Literal["info", "warning", "critical"]

SYNTHETIC_LANE_ID = "monitoring-hotpath-synthetic"
SYNTHETIC_PROJECT = "pitchai_monitoring"
SYNTHETIC_NAME = "Monitoring hotpath protocol synthetic"
SYNTHETIC_TARGET = "monitoring.pitchai.net/dashboard#hotpaths"
_MIN_LANE_COUNT = 13
_decode_json = cast("Callable[[str], JsonValue]", json.loads)


class HotpathContractError(ValueError):
    """A report or inventory violates the versioned hotpath contract."""


@dataclass(frozen=True)
class HotpathLane:
    """One canonical client hotpath lane."""

    lane_id: str
    agent_global_id: str
    project: str
    name: str
    target_surface: str
    reminder_id: str
    expected_behavior: str


@dataclass(frozen=True)
class HotpathInventory:
    """Versioned set of canonical hotpath lanes and timing policy."""

    schema_version: int
    reviewed_at: str
    canonical_tag: str
    expected_interval_seconds: int
    stale_after_seconds: int
    incident_cooldown_seconds: int
    lanes: tuple[HotpathLane, ...]


class HotpathReportRequest(pydantic.BaseModel):
    """Versioned, fail-closed report accepted from one hotpath runner."""

    model_config: ClassVar[pydantic.ConfigDict] = pydantic.ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal[1]
    lane_id: str = pydantic.Field(min_length=3, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]+$")
    project: str = pydantic.Field(min_length=2, max_length=120)
    name: str = pydantic.Field(min_length=2, max_length=200)
    target_surface: str = pydantic.Field(min_length=3, max_length=1000)
    occurred_at: pydantic.AwareDatetime
    source_sha: str = pydantic.Field(pattern=r"^[0-9a-f]{40}$")
    success: bool
    severity: Severity
    failure_reason: str | None = pydantic.Field(default=None, max_length=4000)
    failure_class: str | None = pydantic.Field(default=None, max_length=120)
    failure_phase: str | None = pydantic.Field(default=None, max_length=120)
    evidence_uri: str = pydantic.Field(min_length=20, max_length=3000)
    duration_seconds: float = pydantic.Field(ge=0, le=86400)
    artifact_receipt_sha256: str = pydantic.Field(pattern=r"^[0-9a-f]{64}$")
    run_id: str = pydantic.Field(min_length=3, max_length=240)
    deployed_sha: str | None = pydantic.Field(default=None, pattern=r"^[0-9a-f]{40}$")
    synthetic: bool = False
    synthetic_scenario: str | None = pydantic.Field(default=None, max_length=120)
    exercise_event_bus: bool = False

    @pydantic.model_validator(mode="after")
    def validate_semantics(self) -> Self:
        """Reject contradictory success, severity, and proof fields.

        Returns:
            The validated report.

        Raises:
            HotpathContractError: If report fields contradict the protocol.
        """
        error: str | None = None
        if self.success and self.severity == "critical":
            error = "a successful report cannot be critical"
        elif not self.success and self.severity == "info":
            error = "a failed report must be warning or critical"
        elif self.success and self.failure_reason:
            error = "a successful report cannot include failure_reason"
        elif not self.success and not self.failure_reason:
            error = "a failed report requires failure_reason"
        elif self.synthetic != (self.lane_id == SYNTHETIC_LANE_ID):
            error = "synthetic reports must use the reserved synthetic lane"
        elif self.synthetic and not self.synthetic_scenario:
            error = "synthetic reports require synthetic_scenario"
        elif self.exercise_event_bus and not self.synthetic:
            error = "exercise_event_bus is reserved for safe synthetic proof"
        proof_prefix = (
            "s3://pitchai-hotpath-artifacts/client-hotpaths/v1/"
            f"{self.lane_id}/{self.source_sha}/"
        )
        evidence_uri = str(self.evidence_uri)
        if not evidence_uri.startswith(proof_prefix) or ".." in evidence_uri:
            error = "evidence_uri must use the canonical private SeaweedFS prefix"
        if error is not None:
            raise HotpathContractError(error)
        return self

    def canonical_payload(self) -> dict[str, JsonValue]:
        """Return the exact strict-JSON identity document for this report.

        Returns:
            A stable report mapping suitable for hashing.
        """
        occurred_at = self.occurred_at.isoformat(timespec="microseconds")
        return {
            "artifact_receipt_sha256": self.artifact_receipt_sha256,
            "deployed_sha": self.deployed_sha,
            "duration_seconds": self.duration_seconds,
            "evidence_uri": self.evidence_uri,
            "exercise_event_bus": self.exercise_event_bus,
            "failure_class": self.failure_class,
            "failure_phase": self.failure_phase,
            "failure_reason": self.failure_reason,
            "lane_id": self.lane_id,
            "name": self.name,
            "occurred_at": occurred_at.replace("+00:00", "Z"),
            "project": self.project,
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "severity": self.severity,
            "source_sha": self.source_sha,
            "success": self.success,
            "synthetic": self.synthetic,
            "synthetic_scenario": self.synthetic_scenario,
            "target_surface": self.target_surface,
        }


def load_inventory(path: str) -> HotpathInventory:
    """Read and validate the checked-in canonical lane inventory.

    Returns:
        The validated inventory.

    Raises:
        HotpathContractError: If the inventory is incomplete or malformed.
    """
    root = _mapping(_decode_json(Path(path).read_text(encoding="utf-8")), "inventory")
    raw_lanes = _list(root.get("lanes"), "inventory.lanes")
    lanes = tuple(_parse_lane(item, index) for index, item in enumerate(raw_lanes))
    lane_ids = {lane.lane_id for lane in lanes}
    if len(lanes) < _MIN_LANE_COUNT or len(lane_ids) != len(lanes):
        error = "hotpath inventory must contain at least 13 unique lanes"
        raise HotpathContractError(error)
    return HotpathInventory(
        schema_version=_integer(root, "schema_version"),
        reviewed_at=_string(root, "reviewed_at"),
        canonical_tag=_string(root, "canonical_tag"),
        expected_interval_seconds=_integer(root, "expected_interval_seconds"),
        stale_after_seconds=_integer(root, "stale_after_seconds"),
        incident_cooldown_seconds=_integer(root, "incident_cooldown_seconds"),
        lanes=lanes,
    )


def validate_report_identity(
    report: HotpathReportRequest,
    inventory: HotpathInventory,
) -> HotpathLane | None:
    """Bind caller-supplied identity fields to the canonical inventory.

    Returns:
        The canonical lane, or ``None`` for the reserved synthetic lane.

    Raises:
        HotpathContractError: If the supplied identity is not canonical.
    """
    if report.synthetic:
        if (report.project, report.name, report.target_surface) != (
            SYNTHETIC_PROJECT,
            SYNTHETIC_NAME,
            SYNTHETIC_TARGET,
        ):
            error = "synthetic report identity does not match the reserved contract"
            raise HotpathContractError(error)
        return None
    lane = next((item for item in inventory.lanes if item.lane_id == report.lane_id), None)
    if lane is None:
        error = "unknown canonical hotpath lane"
        raise HotpathContractError(error)
    report_identity = (report.project, report.name, report.target_surface)
    canonical_identity = (lane.project, lane.name, lane.target_surface)
    if report_identity != canonical_identity:
        error = "report identity does not match the canonical hotpath inventory"
        raise HotpathContractError(error)
    return lane


def _parse_lane(value: JsonValue, index: int) -> HotpathLane:
    row = _mapping(value, f"inventory.lanes[{index}]")
    return HotpathLane(
        lane_id=_string(row, "lane_id"),
        agent_global_id=_string(row, "agent_global_id"),
        project=_string(row, "project"),
        name=_string(row, "name"),
        target_surface=_string(row, "target_surface"),
        reminder_id=_string(row, "reminder_id"),
        expected_behavior=_string(row, "expected_behavior"),
    )


def _mapping(value: JsonValue, path: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        error = f"{path} must be an object"
        raise HotpathContractError(error)
    return value


def _list(value: JsonValue | None, path: str) -> list[JsonValue]:
    if not isinstance(value, list):
        error = f"{path} must be an array"
        raise HotpathContractError(error)
    return value


def _string(row: dict[str, JsonValue], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        error = f"{key} must be a non-empty string"
        raise HotpathContractError(error)
    return value.strip()


def _integer(row: dict[str, JsonValue], key: str) -> int:
    value = row.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        error = f"{key} must be a positive integer"
        raise HotpathContractError(error)
    return value
