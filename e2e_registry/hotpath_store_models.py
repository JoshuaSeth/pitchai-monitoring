# Copyright (c) 2026 PitchAI. All rights reserved.
"""Internal value objects for hotpath report persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .hotpath_types import JsonValue


@dataclass(frozen=True)
class IngestedReport:
    """Stable server receipt plus whether this request was already stored."""

    receipt: dict[str, JsonValue]
    duplicate: bool


@dataclass(frozen=True)
class LaneState:
    """Latest transition and escalation state for one canonical lane."""

    current_success: bool
    latest_occurred_at_ts: float
    fail_streak: int
    success_streak: int
    last_event_fingerprint: str | None
    last_event_at_ts: float | None


@dataclass(frozen=True)
class StateUpdate:
    """Next lane-state counters and currently open incident identity."""

    fail_streak: int
    success_streak: int
    last_event_fingerprint: str | None
    last_event_at_ts: float | None


@dataclass(frozen=True)
class IncidentDecision:
    """Atomic state and event decision for one non-duplicate report."""

    action: str
    event_kind: str | None
    fingerprint: str | None
    event_fingerprint: str | None
    update_state: bool
    next_state: StateUpdate


@dataclass(frozen=True)
class PersistenceReceipt:
    """Stable identities and serialized receipt for one report insertion."""

    report_id: str
    canonical_report: str
    receipt_json: str
    receipt_hash: str
    received_at_ts: float
