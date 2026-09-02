# Copyright (c) 2026 PitchAI. All rights reserved.
"""Events Bus contracts for independently observed scheduler-cell incidents."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, NamedTuple, cast

from .domain_event_models import DomainTransitionEvent
from .json_types import json_object

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .json_types import JsonInput, JsonObject


class SchedulerCellIncident(NamedTuple):
    """Immutable inputs for one newly open scheduler-cell incident."""

    slug: str
    condition: str
    reason: str
    evidence: Sequence[str]
    failed_since: float


def scheduler_cell_failure_event(
    incident: SchedulerCellIncident,
    *,
    occurred_at: float,
) -> DomainTransitionEvent:
    """Build one critical cell-supervision transition for the shared receiver.

    Returns:
        A complete immutable production-failure event.
    """
    incident_key = _incident_key(incident.slug, incident.condition)
    fingerprint = _fingerprint(incident_key, failed_since=incident.failed_since)
    details = _common_details(
        slug=incident.slug,
        condition=incident.condition,
        incident_key=incident_key,
        fingerprint=fingerprint,
    )
    details.update(
        {
            "severity": "critical",
            "reason": incident.reason[:500],
            "error": incident.reason[:500],
            "detected_at_ts": occurred_at,
            "failed_since_ts": incident.failed_since,
            "evidence": [line[:800] for line in incident.evidence[:20]],
            "repair_dispatch": (
                "Inspect the affected cell, restore its app-server/control-plane path or storage headroom, "
                "then verify central heartbeat and projection recovery."
            ),
            "incident_update": "new_failure",
        },
    )
    return DomainTransitionEvent(kind="production_failure", occurred_at=occurred_at, details=details)


def scheduler_cell_recovered_event(
    *,
    slug: str,
    condition: str,
    fingerprint: str,
    evidence: Sequence[str],
    occurred_at: float,
) -> DomainTransitionEvent:
    """Build one recovery linked to the exact open cell incident.

    Returns:
        A complete immutable production-recovery event.
    """
    details = _common_details(
        slug=slug,
        condition=condition,
        incident_key=_incident_key(slug, condition),
        fingerprint=fingerprint,
    )
    details.update(
        {
            "severity": "info",
            "recovered_at_ts": occurred_at,
            "evidence": [line[:800] for line in evidence[:20]],
            "repair_dispatch": "Verify the recovered cell remains fresh and reconcile its existing incident lane.",
            "incident_update": "recovered",
        },
    )
    return DomainTransitionEvent(kind="production_recovered", occurred_at=occurred_at, details=details)


def _common_details(
    *,
    slug: str,
    condition: str,
    incident_key: str,
    fingerprint: str,
) -> JsonObject:
    return json_object(
        cast(
            "JsonInput",
            {
                "service": "pitchai-platform-cell-supervision",
                "site": slug,
                "surface_kind": condition,
                "target_environment": "production",
                "project_id": "pitchai_cli_new",
                "owner_project": "pitchai_cli_new",
                "project_group": "platform",
                "customer_group": "internal",
                "group_label": "PitchAI platform",
                "incident_key": incident_key,
                "incident_fingerprint": fingerprint,
                "alertable": True,
                "critical": True,
                "suppressed": False,
                "synthetic": False,
                "expected_behavior": (
                    "Every scheduling cell must publish a fresh central heartbeat, expose bounded direct-delivery "
                    "acceptance health, and report root and selected work-storage capacity independently."
                ),
                "likely_fix_path": (
                    "Use central directory evidence to distinguish cell outage, app-server/SQLite delivery stall, "
                    "root-disk pressure, and selected new-lane storage pressure. Preserve existing lane ownership."
                ),
                "affected_apps": ["pitchai-cli-new", "pitchai-work-inbox"],
                "outgoing_message_boundary": (
                    "This producer grants no outgoing-message authority; receiver policy owns any notification route."
                ),
            },
        ),
    )


def _incident_key(slug: str, condition: str) -> str:
    return f"scheduler:cell:{slug}:{condition}"


def _fingerprint(incident_key: str, *, failed_since: float) -> str:
    encoded = f"{incident_key}\0{failed_since:.6f}".encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
