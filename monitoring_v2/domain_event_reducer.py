# Copyright (c) 2026 PitchAI. All rights reserved.
"""Reduce retained domain transitions into deduplicated critical incidents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .domain_event_contract import domain_down_event, domain_up_event
from .domain_event_models import (
    DomainIncidentReceipt,
    DomainProducerState,
    DomainReduction,
    DomainReductionBuffer,
)
from .domain_event_state import MAX_SEEN_EVENTS, retained_event_id
from .event_analysis import safe_events
from .json_types import bool_value, float_value, optional_object, text_value

if TYPE_CHECKING:
    from .domain_event_models import DomainIncidentPolicy, DomainTransitionEvent
    from .json_types import JsonObject

_DOMAIN_DOWN = "domain_down"
_DOMAIN_UP = "domain_up"
_CONSUMER_COOLDOWN_SECONDS = 1_800.0
_REESCALATION_SECONDS = 1_860.0


def reduce_domain_events(
    *,
    policies: dict[str, DomainIncidentPolicy],
    source_state: JsonObject,
    retained: DomainProducerState,
    now: float,
) -> DomainReduction:
    """Return one crash-safe producer reduction from the legacy collector state.

    Returns:
        Updated producer metadata and immutable transitions to checkpoint.
    """
    transitions = _domain_transitions(source_state)
    seen_order = list(retained.seen_event_ids)
    seen = set(seen_order)
    incidents = retained.incidents.copy()
    outgoing: list[DomainTransitionEvent] = []
    buffer = DomainReductionBuffer(incidents=incidents, outgoing=outgoing, now=now)
    changed = False

    if not retained.bootstrapped:
        for event in transitions:
            _remember_event(event, seen=seen, seen_order=seen_order)
        _reconcile_current(
            policies=policies,
            source_state=source_state,
            transitions=transitions,
            buffer=buffer,
        )
        changed = True
    else:
        for event in transitions:
            event_id = retained_event_id(event)
            if event_id in seen:
                continue
            _remember_event(event, seen=seen, seen_order=seen_order)
            _apply_transition(
                event,
                policies=policies,
                buffer=buffer,
            )
            changed = True
        reconciled = _reconcile_current(
            policies=policies,
            source_state=source_state,
            transitions=transitions,
            buffer=buffer,
        )
        changed = changed or reconciled

    updated = DomainProducerState(
        bootstrapped=True,
        seen_event_ids=tuple(seen_order[-MAX_SEEN_EVENTS:]),
        incidents=incidents,
        outbox=retained.outbox,
        updated_at_ts=now if changed else retained.updated_at_ts,
        last_error=retained.last_error,
        last_delivery_id=retained.last_delivery_id,
        last_receiver_event_id=retained.last_receiver_event_id,
        last_delivered_at_ts=retained.last_delivered_at_ts,
    )
    return DomainReduction(state=updated, events=tuple(outgoing))


def _domain_transitions(source_state: JsonObject) -> list[JsonObject]:
    retained_events = safe_events(source_state.get("events"))
    domain_events = (event for event in retained_events if text_value(event.get("kind")) in {_DOMAIN_DOWN, _DOMAIN_UP})
    return list(domain_events)


def _remember_event(event: JsonObject, *, seen: set[str], seen_order: list[str]) -> None:
    event_id = retained_event_id(event)
    if event_id not in seen:
        seen.add(event_id)
        seen_order.append(event_id)


def _apply_transition(
    event: JsonObject,
    *,
    policies: dict[str, DomainIncidentPolicy],
    buffer: DomainReductionBuffer,
) -> None:
    domain = text_value(event.get("domain"))
    policy = policies.get(domain)
    if policy is None:
        return
    kind = text_value(event.get("kind"))
    occurred_at = float_value(event.get("ts")) or buffer.now
    if kind == _DOMAIN_DOWN and policy.alertable and _retained_alertable(event):
        _stage_down(
            policy,
            event,
            buffer=buffer,
            occurred_at=occurred_at,
            re_escalation=False,
        )
    elif kind == _DOMAIN_UP and domain in buffer.incidents:
        prior = buffer.incidents.pop(domain)
        buffer.outgoing.append(
            domain_up_event(
                policy,
                incident_fingerprint=prior.fingerprint,
                occurred_at=occurred_at,
            ),
        )


def _reconcile_current(
    *,
    policies: dict[str, DomainIncidentPolicy],
    source_state: JsonObject,
    transitions: list[JsonObject],
    buffer: DomainReductionBuffer,
) -> bool:
    changed = False
    statuses = optional_object(source_state.get("last_ok"))
    for domain, policy in sorted(policies.items()):
        prior = buffer.incidents.get(domain)
        status = bool_value(statuses.get(domain))
        if not policy.alertable:
            if prior is not None:
                buffer.incidents.pop(domain, None)
                changed = True
            continue
        if status is False:
            evidence = _latest_down(transitions, domain=domain) or {
                "ts": buffer.now,
                "kind": _DOMAIN_DOWN,
                "domain": domain,
                "reason": "debounced production domain state is down",
                "telegram_alert": True,
            }
            due = prior is None or buffer.now - prior.last_event_at_ts >= _REESCALATION_SECONDS
            if due and _retained_alertable(evidence):
                _stage_down(
                    policy,
                    evidence,
                    buffer=buffer,
                    occurred_at=buffer.now,
                    re_escalation=prior is not None,
                )
                changed = True
        elif status is True and prior is not None:
            buffer.incidents.pop(domain, None)
            buffer.outgoing.append(
                domain_up_event(policy, incident_fingerprint=prior.fingerprint, occurred_at=buffer.now),
            )
            changed = True
    return changed


def _stage_down(
    policy: DomainIncidentPolicy,
    evidence: JsonObject,
    *,
    buffer: DomainReductionBuffer,
    occurred_at: float,
    re_escalation: bool,
) -> None:
    event = domain_down_event(
        policy,
        evidence,
        occurred_at=occurred_at,
        re_escalation=re_escalation,
    )
    fingerprint = text_value(event.details.get("incident_fingerprint"))
    prior = buffer.incidents.get(policy.domain)
    duplicate_inside_cooldown = (
        prior is not None
        and prior.fingerprint == fingerprint
        and buffer.now - prior.last_event_at_ts < _CONSUMER_COOLDOWN_SECONDS
    )
    if duplicate_inside_cooldown:
        return
    buffer.incidents[policy.domain] = DomainIncidentReceipt(fingerprint, buffer.now)
    buffer.outgoing.append(event)


def _latest_down(transitions: list[JsonObject], *, domain: str) -> JsonObject:
    reversed_transitions = reversed(transitions)
    down_transitions = (event for event in reversed_transitions if text_value(event.get("kind")) == _DOMAIN_DOWN)
    matching_domains = (event for event in down_transitions if text_value(event.get("domain")) == domain)
    empty: JsonObject = {}
    return next(matching_domains, empty)


def _retained_alertable(event: JsonObject) -> bool:
    telegram_alert = bool_value(event.get("telegram_alert"))
    return telegram_alert is not False
