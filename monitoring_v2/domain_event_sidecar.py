# Copyright (c) 2026 PitchAI. All rights reserved.
"""Run durable critical production-event enrichment beside the collector."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .domain_event_models import DomainCycleReceipt, DomainProducerState
from .domain_event_policy import domain_incident_policies
from .domain_event_reducer import reduce_domain_events
from .domain_event_state import (
    domain_producer_state_value,
    empty_domain_producer_state,
    load_domain_producer_state,
)
from .domain_runtime import load_config
from .event_bus_delivery import DatabaseEventBus
from .event_bus_runtime import EVENT_BUS_RUNTIME
from .json_types import json_object, normalize_json, object_list
from .production_event_reducer import ProductionReductionContext, reduce_production_events
from .state_io import load_state, write_state

if TYPE_CHECKING:
    from httpx import BaseTransport

    from .event_bus_runtime import DeliveryAttempt
    from .json_types import JsonInput, JsonObject

LOGGER = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = "domain_checks/config.yaml"
_DEFAULT_SOURCE_PATH = "/data/state.json"
_DEFAULT_STATE_PATH = "/data/domain-incident-events.json"
_DEFAULT_POLL_SECONDS = 5.0
_MAX_POLL_SECONDS = 60.0


def run_cycle(
    *,
    config_path: Path,
    source_path: Path,
    state_path: Path,
    now: float | None = None,
    transport: BaseTransport | None = None,
) -> DomainCycleReceipt:
    """Reduce, checkpoint, and flush one bounded producer cycle.

    Returns:
        An inspectable cycle receipt. Missing source state remains a first-run wait.

    """
    selected_now = time.time() if now is None else now
    if not source_path.exists():
        return DomainCycleReceipt("waiting_for_source", 0, 0, 0)
    retained = load_domain_producer_state(state_path)
    reduced_state, staged_bus, staged_count = _staged_cycle(
        config_path=config_path,
        source_path=source_path,
        retained=retained,
        now=selected_now,
    )
    checkpoint = _checkpoint_state(
        reduced_state,
        outbox=object_list(staged_bus.state_value()),
        now=selected_now,
    )
    if domain_producer_state_value(checkpoint) != domain_producer_state_value(retained):
        write_state(state_path, domain_producer_state_value(checkpoint))

    attempts = staged_bus.flush(now=selected_now, transport=transport)
    delivered = sum(attempt.success for attempt in attempts)
    final_state = _delivery_state(
        checkpoint,
        outbox=object_list(staged_bus.state_value()),
        attempts=attempts,
        now=selected_now,
    )
    if domain_producer_state_value(final_state) != domain_producer_state_value(checkpoint):
        write_state(state_path, domain_producer_state_value(final_state))
    return DomainCycleReceipt(
        source_status="ready",
        staged_count=staged_count,
        delivered_count=delivered,
        pending_count=len(final_state.outbox),
    )


def _staged_cycle(
    *,
    config_path: Path,
    source_path: Path,
    retained: DomainProducerState,
    now: float,
) -> tuple[DomainProducerState, DatabaseEventBus, int]:
    source_state = load_state(source_path)
    config = load_config(config_path)
    policies = domain_incident_policies(config)
    initial_bootstrap = not retained.bootstrapped
    domain_reduction = reduce_domain_events(
        policies=policies,
        source_state=source_state,
        retained=retained,
        now=now,
    )
    production_reduction = reduce_production_events(
        context=ProductionReductionContext(
            policies=policies,
            config=config,
            source_state=source_state,
            now=now,
            initial_bootstrap=initial_bootstrap,
        ),
        retained=domain_reduction.state,
    )
    transitions = tuple(
        sorted(
            (*domain_reduction.events, *production_reduction.events),
            key=lambda event: event.occurred_at,
        ),
    )
    raw_bus_state = {"event_bus_outbox": normalize_json(cast("JsonInput", retained.outbox))}
    event_bus = DatabaseEventBus.from_state(json_object(cast("JsonInput", raw_bus_state)))
    if event_bus is None:
        message = "domain incident Events Bus delivery is not configured"
        raise RuntimeError(message)
    staged_bus = event_bus.staged_events(transitions)
    return production_reduction.state, staged_bus, len(transitions)


def _checkpoint_state(
    state: DomainProducerState,
    *,
    outbox: list[JsonObject],
    now: float,
) -> DomainProducerState:
    return DomainProducerState(
        bootstrapped=state.bootstrapped,
        seen_event_ids=state.seen_event_ids,
        incidents=state.incidents,
        outbox=outbox,
        updated_at_ts=max(state.updated_at_ts, now if outbox != state.outbox else state.updated_at_ts),
        last_error=state.last_error if outbox else None,
        last_delivery_id=state.last_delivery_id,
        last_receiver_event_id=state.last_receiver_event_id,
        last_delivered_at_ts=state.last_delivered_at_ts,
    )


def _delivery_state(
    state: DomainProducerState,
    *,
    outbox: list[JsonObject],
    attempts: tuple[DeliveryAttempt, ...],
    now: float,
) -> DomainProducerState:
    last_delivery_id = state.last_delivery_id
    last_receiver_event_id = state.last_receiver_event_id
    last_delivered_at = state.last_delivered_at_ts
    last_error = state.last_error
    if attempts:
        for attempt in attempts:
            if not attempt.success:
                continue
            last_delivery_id = attempt.delivery_id or None
            last_receiver_event_id = attempt.event_id
            last_delivered_at = now
        final_attempt = attempts[-1]
        final_error = final_attempt.error
        last_error = None if final_attempt.success else f"event_bus_delivery:{final_error or 'unknown'}"
    return DomainProducerState(
        bootstrapped=state.bootstrapped,
        seen_event_ids=state.seen_event_ids,
        incidents=state.incidents,
        outbox=outbox,
        updated_at_ts=now if attempts else state.updated_at_ts,
        last_error=last_error,
        last_delivery_id=last_delivery_id,
        last_receiver_event_id=last_receiver_event_id,
        last_delivered_at_ts=last_delivered_at,
    )


def _record_cycle_error(state_path: Path, error: BaseException, *, now: float) -> None:
    retained = load_domain_producer_state(state_path) if state_path.exists() else empty_domain_producer_state()
    failed = DomainProducerState(
        bootstrapped=retained.bootstrapped,
        seen_event_ids=retained.seen_event_ids,
        incidents=retained.incidents,
        outbox=retained.outbox,
        updated_at_ts=now,
        last_error=f"cycle_failure:{type(error).__name__}",
        last_delivery_id=retained.last_delivery_id,
        last_receiver_event_id=retained.last_receiver_event_id,
        last_delivered_at_ts=retained.last_delivered_at_ts,
    )
    write_state(state_path, domain_producer_state_value(failed))


def _poll_seconds() -> float:
    raw = os.getenv("DOMAIN_INCIDENT_EVENT_POLL_SECONDS", str(_DEFAULT_POLL_SECONDS))
    selected = float(raw)
    if not 1.0 <= selected <= _MAX_POLL_SECONDS:
        message = "DOMAIN_INCIDENT_EVENT_POLL_SECONDS must be between 1 and 60"
        raise ValueError(message)
    return selected


def _run_and_log_cycle(*, config_path: Path, source_path: Path, state_path: Path) -> None:
    receipt = run_cycle(
        config_path=config_path,
        source_path=source_path,
        state_path=state_path,
    )
    if receipt.staged_count or receipt.delivered_count or receipt.pending_count:
        LOGGER.info("domain incident producer cycle receipt=%s", receipt)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if EVENT_BUS_RUNTIME.load_event_bus_config() is None:
        CONFIGURATION_ERROR = "domain incident Events Bus delivery is not configured"
        raise RuntimeError(CONFIGURATION_ERROR)
    CONFIGURED_CONFIG_PATH = Path(os.getenv("DOMAIN_INCIDENT_CONFIG_PATH", _DEFAULT_CONFIG_PATH))
    CONFIGURED_SOURCE_PATH = Path(os.getenv("STATE_PATH", _DEFAULT_SOURCE_PATH))
    CONFIGURED_STATE_PATH = Path(os.getenv("DOMAIN_INCIDENT_EVENT_STATE_PATH", _DEFAULT_STATE_PATH))
    poll_seconds = _poll_seconds()
    while True:
        cycle_started = time.monotonic()
        try:
            _run_and_log_cycle(
                config_path=CONFIGURED_CONFIG_PATH,
                source_path=CONFIGURED_SOURCE_PATH,
                state_path=CONFIGURED_STATE_PATH,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            LOGGER.exception("domain incident producer cycle failed error_type=%s", type(error).__name__)
            _record_cycle_error(CONFIGURED_STATE_PATH, error, now=time.time())
        elapsed = time.monotonic() - cycle_started
        time.sleep(max(1.0, poll_seconds - elapsed))
