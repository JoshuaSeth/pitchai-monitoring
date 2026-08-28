# Copyright (c) 2026 PitchAI. All rights reserved.
"""Reduce critical app-surface state into production incident transitions."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from .domain_event_models import (
    DomainIncidentReceipt,
    DomainProducerState,
    DomainReduction,
)
from .domain_event_state import MAX_SEEN_EVENTS, retained_event_id
from .event_analysis import safe_events
from .json_types import bool_value, float_value, text_value
from .production_event_contract import production_failure_event, production_recovered_event
from .production_event_routes import current_production_routes, production_route_for_event

if TYPE_CHECKING:
    from .domain_event_models import DomainIncidentPolicy, DomainTransitionEvent, ProductionIncidentRoute
    from .json_types import JsonObject

_OPEN_TO_SIGNAL = {
    "api_contract_degraded": "api_contract",
    "synthetic_degraded": "synthetic_transaction",
    "proxy_degraded": "reverse_proxy",
}
_RECOVERY_TO_SIGNAL = {
    "api_contract_recovered": "api_contract",
    "synthetic_recovered": "synthetic_transaction",
    "proxy_recovered": "reverse_proxy",
}
_CONSUMER_COOLDOWN_SECONDS = 1_800.0
_REESCALATION_SECONDS = 1_860.0


class ProductionReductionContext(NamedTuple):
    """Immutable inputs shared across one app-surface reduction."""

    policies: dict[str, DomainIncidentPolicy]
    config: JsonObject
    source_state: JsonObject
    now: float
    initial_bootstrap: bool


class _ReductionBuffer(NamedTuple):
    incidents: dict[str, DomainIncidentReceipt]
    outgoing: list[DomainTransitionEvent]
    now: float


def reduce_production_events(
    *,
    context: ProductionReductionContext,
    retained: DomainProducerState,
) -> DomainReduction:
    """Return new critical app failures without promoting noisy degradation."""
    transitions = _production_transitions(context.source_state)
    seen_order = list(retained.seen_event_ids)
    seen = set(seen_order)
    incidents = retained.incidents.copy()
    outgoing: list[DomainTransitionEvent] = []
    buffer = _ReductionBuffer(incidents=incidents, outgoing=outgoing, now=context.now)

    if context.initial_bootstrap:
        for event in transitions:
            _remember_event(event, seen=seen, seen_order=seen_order)
    else:
        unseen = [event for event in transitions if retained_event_id(event) not in seen]
        for event in unseen:
            _remember_event(event, seen=seen, seen_order=seen_order)
            _apply_transition(
                event,
                context=context,
                buffer=buffer,
            )

    reconciled = _reconcile_current(
        context=context,
        transitions=transitions,
        buffer=buffer,
    )
    changed = bool(outgoing) or reconciled or context.initial_bootstrap or tuple(seen_order) != retained.seen_event_ids
    updated = DomainProducerState(
        bootstrapped=True,
        seen_event_ids=tuple(seen_order[-MAX_SEEN_EVENTS:]),
        incidents=incidents,
        outbox=retained.outbox,
        updated_at_ts=context.now if changed else retained.updated_at_ts,
        last_error=retained.last_error,
        last_delivery_id=retained.last_delivery_id,
        last_receiver_event_id=retained.last_receiver_event_id,
        last_delivered_at_ts=retained.last_delivered_at_ts,
    )
    return DomainReduction(state=updated, events=tuple(outgoing))


def _production_transitions(source_state: JsonObject) -> list[JsonObject]:
    kinds = set(_OPEN_TO_SIGNAL) | set(_RECOVERY_TO_SIGNAL)
    return [event for event in safe_events(source_state.get("events")) if text_value(event.get("kind")) in kinds]


def _remember_event(event: JsonObject, *, seen: set[str], seen_order: list[str]) -> None:
    event_id = retained_event_id(event)
    if event_id not in seen:
        seen.add(event_id)
        seen_order.append(event_id)


def _apply_transition(
    event: JsonObject,
    *,
    context: ProductionReductionContext,
    buffer: _ReductionBuffer,
) -> None:
    kind = text_value(event.get("kind"))
    signal = _OPEN_TO_SIGNAL.get(kind)
    route = production_route_for_event(
        event,
        signal=signal,
        policies=context.policies,
        config=context.config,
    )
    occurred_at = float_value(event.get("ts")) or context.now
    if route is not None and signal is not None and _retained_alertable(event):
        _stage_failure(route, event, buffer=buffer, occurred_at=occurred_at)
        return
    recovery_signal = _RECOVERY_TO_SIGNAL.get(kind)
    recovery_route = production_route_for_event(
        event,
        signal=recovery_signal,
        policies=context.policies,
        config=context.config,
    )
    if recovery_route is None:
        return
    prior = buffer.incidents.pop(recovery_route.incident_key, None)
    if prior is not None:
        buffer.outgoing.append(
            production_recovered_event(
                recovery_route,
                incident_fingerprint=prior.fingerprint,
                occurred_at=occurred_at,
            ),
        )


def _reconcile_current(
    *,
    context: ProductionReductionContext,
    transitions: list[JsonObject],
    buffer: _ReductionBuffer,
) -> bool:
    changed = False
    active_routes = current_production_routes(
        policies=context.policies,
        config=context.config,
        source_state=context.source_state,
    )
    active_keys = {route.incident_key for route, _event in active_routes}
    managed_keys = {key for key in buffer.incidents if key.startswith("production:")}
    for inactive_key in sorted(managed_keys - active_keys):
        buffer.incidents.pop(inactive_key, None)
        changed = True
    for route, fallback in active_routes:
        prior = buffer.incidents.get(route.incident_key)
        due = prior is None or context.now - prior.last_event_at_ts >= _REESCALATION_SECONDS
        if not due:
            continue
        evidence = _latest_open(transitions, route=route) or fallback
        if not _retained_alertable(evidence):
            continue
        _stage_failure(
            route,
            evidence,
            buffer=buffer,
            occurred_at=context.now,
            re_escalation=prior is not None,
        )
        changed = True
    return changed


def _stage_failure(
    route: ProductionIncidentRoute,
    evidence: JsonObject,
    *,
    buffer: _ReductionBuffer,
    occurred_at: float,
    re_escalation: bool = False,
) -> None:
    event = production_failure_event(route, evidence, occurred_at=occurred_at, re_escalation=re_escalation)
    fingerprint = text_value(event.details.get("incident_fingerprint"))
    prior = buffer.incidents.get(route.incident_key)
    duplicate_inside_cooldown = (
        prior is not None
        and prior.fingerprint == fingerprint
        and buffer.now - prior.last_event_at_ts < _CONSUMER_COOLDOWN_SECONDS
    )
    if duplicate_inside_cooldown:
        return
    buffer.incidents[route.incident_key] = DomainIncidentReceipt(fingerprint, buffer.now)
    buffer.outgoing.append(event)


def _latest_open(transitions: list[JsonObject], *, route: ProductionIncidentRoute) -> JsonObject:
    expected_kind = next((kind for kind, signal in _OPEN_TO_SIGNAL.items() if signal == route.signal), "")
    candidates = [event for event in transitions if text_value(event.get("kind")) == expected_kind]
    if route.domain is not None:
        candidates = [event for event in candidates if text_value(event.get("domain")) == route.domain]
    return max(candidates, key=lambda event: float_value(event.get("ts")) or 0.0) if candidates else {}


def _retained_alertable(event: JsonObject) -> bool:
    return bool_value(event.get("telegram_alert")) is not False
