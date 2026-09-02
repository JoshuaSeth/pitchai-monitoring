# Copyright (c) 2026 PitchAI. All rights reserved.
"""Reduce central cell snapshots into durable scheduler supervision incidents."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, cast

from .json_types import bool_value, float_value, json_object, optional_object, text_value
from .scheduler_cell_directory import pressure_number
from .scheduler_cell_event import SchedulerCellIncident, scheduler_cell_failure_event, scheduler_cell_recovered_event
from .scheduler_cell_signals import scheduler_cell_signals

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .domain_event_models import DomainTransitionEvent
    from .json_types import JsonInput, JsonObject
    from .scheduler_cell_directory import SchedulerCellObservation
    from .scheduler_cell_signals import SchedulerCellSignal

_SCHEDULER_SCHEMA_MINIMUM = 4


class SchedulerCellReduction(NamedTuple):
    """Persistable cell state plus transition events for one directory poll."""

    cells: JsonObject
    events: tuple[DomainTransitionEvent, ...]


def reduce_scheduler_cells(
    observations: Sequence[SchedulerCellObservation],
    *,
    retained_cells: JsonObject,
    now: float,
) -> SchedulerCellReduction:
    """Evaluate fresh liveness, direct acceptance, and storage-root health.

    Returns:
        The updated durable per-cell state and any new transitions.
    """
    updated = optional_object(retained_cells)
    events: list[DomainTransitionEvent] = []
    for observation in observations:
        prior = optional_object(updated.get(observation.slug))
        schema = pressure_number(observation.pressure, "scheduler_schema_version")
        if (schema is None or schema < _SCHEDULER_SCHEMA_MINIMUM) and not prior:
            continue
        conditions = optional_object(prior.get("conditions"))
        feature_seen = "direct_unaccepted_observation_ready" in observation.pressure or bool_value(
            prior.get("direct_metrics_seen"),
        ) is True
        projection_seen = observation.projection_sequence is not None or bool_value(
            prior.get("projection_metrics_seen"),
        ) is True
        signals = scheduler_cell_signals(
            observation,
            direct_feature_seen=feature_seen,
            projection_feature_seen=projection_seen,
            now=now,
        )
        for signal in signals:
            condition, event = _reduce_signal(
                observation,
                signal=signal,
                prior=optional_object(conditions.get(signal.key)),
                now=now,
            )
            conditions[signal.key] = condition
            if event is not None:
                events.append(event)
        updated[observation.slug] = json_object(
            cast(
                "JsonInput",
                {
                    "cell_id": observation.cell_id,
                    "boot_id": observation.boot_id,
                    "last_received_at": observation.last_received_at,
                    "last_seen_at_ts": now,
                    "direct_metrics_seen": feature_seen,
                    "projection_metrics_seen": projection_seen,
                    "conditions": conditions,
                },
            ),
        )
    return SchedulerCellReduction(cells=updated, events=tuple(events))


def _reduce_signal(
    cell: SchedulerCellObservation,
    *,
    signal: SchedulerCellSignal,
    prior: JsonObject,
    now: float,
) -> tuple[JsonObject, DomainTransitionEvent | None]:
    if signal.failed is None:
        return prior, None
    was_open = bool_value(prior.get("open")) is True
    prior_since = float_value(prior.get("failed_since_ts"))
    prior_fingerprint = text_value(prior.get("fingerprint"))
    if signal.failed:
        failed_since = now if prior_since is None else prior_since
        due = now - failed_since >= signal.grace_seconds
        event = None
        fingerprint = prior_fingerprint or None
        if due and not was_open:
            event = scheduler_cell_failure_event(
                SchedulerCellIncident(
                    slug=cell.slug,
                    condition=signal.key,
                    reason=signal.reason,
                    evidence=signal.evidence,
                    failed_since=failed_since,
                ),
                occurred_at=now,
            )
            fingerprint = text_value(event.details.get("incident_fingerprint"))
        return json_object(
            {
                "open": was_open or due,
                "failed_since_ts": failed_since,
                "fingerprint": fingerprint,
            },
        ), event
    recovery = None
    if was_open and prior_fingerprint:
        recovery = scheduler_cell_recovered_event(
            slug=cell.slug,
            condition=signal.key,
            fingerprint=prior_fingerprint,
            evidence=signal.evidence,
            occurred_at=now,
        )
    return json_object({"open": False, "failed_since_ts": None, "fingerprint": None}), recovery
