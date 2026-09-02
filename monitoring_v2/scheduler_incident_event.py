# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict scheduler-failure adapter for the shared monitoring Events Bus."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from .domain_event_models import DomainTransitionEvent
from .json_types import json_object, object_list, text_value

if TYPE_CHECKING:
    from .json_types import JsonInput, JsonObject, JsonValue

_MAX_TEXT = 2_000
_MAX_CELLS = 64
_MAX_CELL_REASONS = 32
_MAX_REASON_CHARACTERS = 512
_MAX_STORAGE_ROOTS = 8
_MAX_STORAGE_REASONS = 8
_MAX_USED_PERCENT = 100
_STORAGE_SIGNAL_SCHEMA = 2


def placement_failure_event(incident: JsonObject) -> DomainTransitionEvent:
    """Convert one validated central failure record to the monitoring contract.

    Returns:
        An immutable shared Events Bus transition.

    Raises:
        ValueError: If the incident schema or timestamp is invalid.
    """
    schema_version = incident.get("signal_schema_version")
    if schema_version not in {1, 2} or incident.get("kind") != "new_lane_placement_failed":
        message = "scheduler incident feed returned an unsupported signal"
        raise ValueError(message)
    occurred_at = required_timestamp(incident, "occurred_at")
    project_key = required_text(incident, "project_key", limit=256)
    origin_branch = required_text(incident, "origin_branch", limit=512)
    summary = required_text(incident, "rejection_summary", limit=_MAX_TEXT)
    cell_evidence, reasons = _cell_evidence(incident, require_storage=schema_version == _STORAGE_SIGNAL_SCHEMA)
    fingerprint = _failure_fingerprint(project_key, origin_branch, cell_evidence)
    incident_key_hash = hashlib.sha256(project_key.encode()).hexdigest()[:20]
    details = json_object(
        cast(
            "JsonInput",
            {
                "service": "pitchai-platform-new-lane-scheduler",
                "site": "PitchAI central control plane",
                "target_environment": "production",
                "severity": "critical",
                "alertable": True,
                "critical": True,
                "suppressed": False,
                "synthetic": False,
                "incident_key": f"scheduler:new-lane-placement:{incident_key_hash}",
                "incident_fingerprint": fingerprint,
                "project_id": "pitchai_cli_new",
                "owner_project": "pitchai_cli_new",
                "project_group": "platform",
                "customer_group": "internal",
                "reason": "terminal automatic new-lane placement failure",
                "error": summary[:500],
                "expected_behavior": (
                    "Safe new work must start on the healthiest cell able to materialize its configured project "
                    "base on the selected writable storage root."
                ),
                "likely_fix_path": (
                    "Inspect per-cell heartbeat, project fetch/materialization credentials, configured source ref, "
                    "root and selected work-storage capacity, CPU/IO pressure, and master-host risk."
                ),
                "affected_apps": ["pitchai-cli-new", "pitchai-work-inbox"],
                "reasons": reasons[:20],
                "evidence": [
                    f"requested project={project_key} configured_base={origin_branch}",
                    *cell_evidence,
                ][:20],
                "repair_dispatch": (
                    "Repair scheduler eligibility or cell capability, then prove a real safe new-lane placement."
                ),
                "outgoing_message_boundary": (
                    "This producer grants no outgoing-message authority; receiver policy owns any notification route."
                ),
            },
        ),
    )
    return DomainTransitionEvent(
        kind="production_failure",
        occurred_at=datetime.fromisoformat(occurred_at).timestamp(),
        details=details,
    )


def required_timestamp(payload: JsonObject, field: str) -> str:
    """Return one normalized, timezone-aware timestamp field.

    Raises:
        ValueError: If the field is not a timezone-aware ISO timestamp.
    """
    value = required_text(payload, field, limit=64)
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        message = f"scheduler incident field {field} must include a timezone"
        raise ValueError(message)
    return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def required_text(payload: JsonObject, field: str, *, limit: int) -> str:
    """Return one non-empty bounded text field.

    Raises:
        TypeError: If the field is absent, empty, or too long.
    """
    value = text_value(payload.get(field))
    if not value.strip() or len(value) > limit:
        message = f"scheduler incident field {field} is invalid"
        raise TypeError(message)
    return value.strip()


def _cell_evidence(incident: JsonObject, *, require_storage: bool) -> tuple[list[str], list[str]]:
    raw_cells = incident.get("cells")
    cells = object_list(raw_cells)
    if not isinstance(raw_cells, list) or len(cells) != len(raw_cells) or len(cells) > _MAX_CELLS:
        message = "scheduler incident cells must be a bounded object array"
        raise TypeError(message)
    evidence: list[str] = []
    flattened_reasons: list[str] = []
    for cell in cells:
        slug = required_text(cell, "slug", limit=63)
        raw_reasons = cell.get("reasons")
        if not isinstance(raw_reasons, list) or not 1 <= len(raw_reasons) <= _MAX_CELL_REASONS:
            message = "scheduler incident cell reasons must be a bounded text array"
            raise TypeError(message)
        reasons = [_bounded_reason(reason) for reason in raw_reasons]
        evidence.append(f"{slug} rejected: {'; '.join(reasons)}"[:500])
        flattened_reasons.extend(f"{slug}: {reason}"[:500] for reason in reasons)
        evidence.extend(_storage_evidence(cell, slug=slug, required=require_storage))
    return evidence, flattened_reasons


def _storage_evidence(cell: JsonObject, *, slug: str, required: bool) -> list[str]:
    raw_roots = cell.get("storage_roots")
    roots = object_list(raw_roots)
    if raw_roots is None and not required:
        return []
    if not isinstance(raw_roots, list) or len(roots) != len(raw_roots) or not 1 <= len(roots) <= _MAX_STORAGE_ROOTS:
        message = "scheduler incident storage roots must be a bounded object array"
        raise TypeError(message)
    return [_storage_root_evidence(root, slug=slug) for root in roots]


def _storage_root_evidence(root: JsonObject, *, slug: str) -> str:
    path = required_text(root, "path", limit=512)
    role = required_text(root, "role", limit=16)
    if role not in {"root", "new_lane"}:
        message = "scheduler incident storage root role is invalid"
        raise TypeError(message)
    selected = root.get("selected_for_new_lanes")
    same_device = root.get("same_device_as_root")
    used = root.get("used_percent")
    free = root.get("free_bytes")
    if not isinstance(selected, bool) or (same_device is not None and not isinstance(same_device, bool)):
        message = "scheduler incident storage root flags are invalid"
        raise TypeError(message)
    if used is not None and (
        isinstance(used, bool) or not isinstance(used, int | float) or not 0 <= used <= _MAX_USED_PERCENT
    ):
        message = "scheduler incident storage used percentage is invalid"
        raise TypeError(message)
    if free is not None and (isinstance(free, bool) or not isinstance(free, int) or free < 0):
        message = "scheduler incident storage free bytes are invalid"
        raise TypeError(message)
    raw_reasons = root.get("reasons")
    if not isinstance(raw_reasons, list) or len(raw_reasons) > _MAX_STORAGE_REASONS:
        message = "scheduler incident storage reasons are invalid"
        raise TypeError(message)
    root_reasons = [_bounded_reason(reason) for reason in raw_reasons]
    rendered_used = "unknown" if used is None else f"{float(used):.1f}%"
    rendered_free = "unknown" if free is None else f"{free / 1024**3:.1f}GiB"
    relationship = "unknown" if same_device is None else ("root-device" if same_device else "separate-device")
    suffix = "" if not root_reasons else f" reasons={'; '.join(root_reasons)}"
    return (
        f"{slug} storage role={role} path={path} selected={str(selected).lower()} used={rendered_used} "
        f"free={rendered_free} device={relationship}{suffix}"[:500]
    )


def _bounded_reason(value: JsonValue) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_REASON_CHARACTERS:
        message = "scheduler incident rejection reason is invalid"
        raise TypeError(message)
    return value.strip()


def _failure_fingerprint(project_key: str, origin_branch: str, evidence: list[str]) -> str:
    encoded = json.dumps(
        {"project_key": project_key, "origin_branch": origin_branch, "cells": evidence},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
