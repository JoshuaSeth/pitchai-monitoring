# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed state and policy models for production domain incident delivery."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from .json_types import JsonObject


class DomainIncidentPolicy(NamedTuple):
    """Canonical inventory and check metadata for one monitored domain."""

    domain: str
    label: str
    group: str
    group_label: str
    environment: str
    surface_kind: str
    owner_project: str
    source_url: str
    allowed_status_codes: tuple[int, ...]
    expected_final_host_suffix: str | None
    expected_final_path: str | None
    expected_title_contains: str | None
    alert_mode: str
    alert_reason: str | None
    disabled: bool
    sources: tuple[str, ...]

    @property
    def alertable(self) -> bool:
        """Return whether this is an active critical production route."""
        return self.environment == "production" and self.alert_mode == "critical" and not self.disabled


class DomainIncidentReceipt(NamedTuple):
    """Producer-side dedupe and re-escalation receipt for one open incident."""

    fingerprint: str
    last_event_at_ts: float


class ProductionIncidentRoute(NamedTuple):
    """Explicit routing and repair context for one critical app surface."""

    signal: str
    site: str
    domain: str | None
    owner_project: str
    project_group: str
    group_label: str
    incident_key: str
    expected_behavior: str
    source_hints: tuple[str, ...]
    logs_hint: str
    likely_fix_path: str


class DomainTransitionEvent(NamedTuple):
    """One complete transition ready for the immutable Events Bus envelope."""

    kind: str
    occurred_at: float
    details: JsonObject


class DomainProducerState(NamedTuple):
    """Durable state owned exclusively by the domain incident sidecar."""

    bootstrapped: bool
    seen_event_ids: tuple[str, ...]
    incidents: dict[str, DomainIncidentReceipt]
    outbox: list[JsonObject]
    updated_at_ts: float
    last_error: str | None
    last_delivery_id: str | None
    last_receiver_event_id: str | None
    last_delivered_at_ts: float | None


class DomainReduction(NamedTuple):
    """One pure state reduction and the transitions it must checkpoint."""

    state: DomainProducerState
    events: tuple[DomainTransitionEvent, ...]


class DomainReductionBuffer(NamedTuple):
    """Mutable collections and clock shared by one pure reduction."""

    incidents: dict[str, DomainIncidentReceipt]
    outgoing: list[DomainTransitionEvent]
    now: float


class DomainCycleReceipt(NamedTuple):
    """Inspectable result of one bounded sidecar cycle."""

    source_status: str
    staged_count: int
    delivered_count: int
    pending_count: int
