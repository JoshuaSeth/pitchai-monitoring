# Copyright (c) 2026 PitchAI. All rights reserved.
"""Content-free DFT checker observations and persistent incident transitions.

The caller owns the existing cycle, atomic state persistence and delivery.
This module does not open retention files, reset the producer latch or send.
"""

from __future__ import annotations

import json
import math
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .event_bus_delivery import JsonValue

_MAX_RESPONSE_BYTES = 32_768
_STALE_SECONDS = 900
_CODES = frozenset({
    "heartbeat_stale", "retention_run_failed", "retention_fault_latched",
    "status_allocation_mismatch", "status_unavailable_or_invalid",
    "unsafe_status_permissions", "oversized_status", "invalid_status_fields",
    "invalid_status_clock", "invalid_status_counts", "invalid_status_errors",
    "invalid_status_identity", "observer_clock_untrusted",
    "observer_clock_discontinuity", "observer_config_invalid",
})


@dataclass(frozen=True)
class CheckerObservation:
    """Only bounded numeric values and fixed failure codes are retained."""

    age_seconds: float | None = None
    overdue_segments: int = 0
    errors: tuple[str, ...] = ()

    @property
    def healthy(self) -> bool:
        """Require positively verified freshness as well as no retained fault."""
        return self.age_seconds is not None and 0 <= self.age_seconds < _STALE_SECONDS and not self.errors


def checker_observation(returncode: int | None, stdout: bytes) -> CheckerObservation:
    """Classify a completed checker invocation without copying arbitrary output.

    A missing return code represents timeout, spawn failure or missing response.
    The process owner must also bound capture while executing the checker.

    Returns:
        A failing observation for every incomplete or inconsistent response.
    """
    if returncode is None:
        return CheckerObservation(errors=("checker_unavailable",))
    if len(stdout) > _MAX_RESPONSE_BYTES:
        return CheckerObservation(errors=("checker_response_oversized",))
    payload: JsonValue = None
    with suppress(ValueError, RecursionError):
        payload = cast("JsonValue", json.loads(stdout))
    if not isinstance(payload, dict):
        return CheckerObservation(errors=("checker_response_invalid",))
    age, overdue, errors = payload.get("age_seconds"), payload.get("overdue_segments"), payload.get("errors")
    valid_age = not isinstance(age, bool) and isinstance(age, (float, int)) and math.isfinite(age) and age >= 0
    valid_count = not isinstance(overdue, bool) and isinstance(overdue, int) and overdue >= 0
    if not valid_count or not isinstance(errors, list) or any(not isinstance(code, str) for code in errors):
        return CheckerObservation(errors=("checker_response_invalid",))
    codes = {code if isinstance(code, str) and code in _CODES else "checker_unrecognized_error" for code in errors}
    if returncode != 0:
        codes.add("checker_nonzero")
    if not valid_age:
        codes.add("checker_age_unavailable")
    elif cast("float", age) >= _STALE_SECONDS:
        codes.add("heartbeat_stale")
    return CheckerObservation(float(cast("float", age)) if valid_age else None,
                              cast("int", overdue), tuple(sorted(codes)))


@dataclass(frozen=True)
class RetentionIncident:
    """Persist this identity before delivery and restore it across restarts."""

    incident_id: str
    opened_at: float
    closed_at: float | None = None
    acknowledged_by_owner: bool = False


def observe_incident(
    current: RetentionIncident | None,
    observation: CheckerObservation,
    *,
    now: float,
    next_incident_id: str,
    owner_acknowledged_incident_id: str | None = None,
) -> RetentionIncident | None:
    """Keep an unresolved identity until owner acknowledgement and healthy proof.

    The next id is allocated by the caller only for a new failure. Repeated
    observations retain the original open/close timestamps, so retries can use
    immutable delivery identities. Acknowledgement alone never closes a fault.

    Returns:
        The retained incident, a new incident, or no incident on initial health.
    """
    if current is None or current.closed_at is not None:
        if observation.healthy:
            return current
        return RetentionIncident(next_incident_id, now)
    acknowledged = current.acknowledged_by_owner or owner_acknowledged_incident_id == current.incident_id
    closed_at = now if acknowledged and observation.healthy else None
    return replace(current, acknowledged_by_owner=acknowledged, closed_at=closed_at)
