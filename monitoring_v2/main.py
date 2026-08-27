# Copyright (c) 2026 PitchAI. All rights reserved.
"""Run the compact production database dependency sidecar."""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

from httpx import HTTPError

from .alerts import (
    DatabaseDependencyAlertConfigurationError,
    DatabaseDependencyAlertDeliveryError,
    deliver_pending_alerts,
)
from .configuration import load_settings
from .discovery import discover_dependencies
from .docker_gateway import DockerGateway
from .event_bus_delivery import DatabaseEventBus
from .json_types import json_object, object_list, text_value
from .probes import execute_probe
from .routing import resolve_routing
from .state import reduce_state
from .state_io import load_state, write_state

if TYPE_CHECKING:
    from .json_types import JsonObject
    from .models import (
        DatabaseDependencySettings,
        ProbeDefinition,
        ProbeObservation,
    )

LOGGER = logging.getLogger(__name__)


def _configured_path(environment_name: str, configured: str) -> Path:
    override = os.getenv(environment_name, "").strip()
    return Path(override or configured)


def _collector_failure_state(
    retained: JsonObject,
    settings: DatabaseDependencySettings,
    *,
    error_class: str,
    observed_at_ts: float,
) -> JsonObject:
    state: JsonObject = retained.copy()
    if not state:
        state = json_object({
            "version": 2,
            "dependencies": [],
            "alert_groups": [],
            "pending_alerts": [],
        })
    dependencies = object_list(state.get("dependencies"))
    prior_status = text_value(state.get("status"))
    state["status"] = "down" if prior_status == "down" else "degraded"
    state["collector"] = json_object({
        "status": "degraded",
        "error_class": error_class,
        "observed_at_ts": observed_at_ts,
        "interval_seconds": settings.interval_seconds,
        "dependency_count": len(dependencies),
    })
    return state


def _execute_one(
    gateway: DockerGateway,
    definition: ProbeDefinition,
    *,
    settings: DatabaseDependencySettings,
    observed_at_ts: float,
) -> ProbeObservation:
    return execute_probe(
        gateway,
        definition,
        python_executable=settings.python_executable,
        timeout_seconds=settings.timeout_seconds,
        observed_at_ts=observed_at_ts,
    )


def _run_cycle(
    gateway: DockerGateway,
    retained: JsonObject,
    settings: DatabaseDependencySettings,
    *,
    observed_at_ts: float,
) -> JsonObject:
    routing = resolve_routing(
        settings.routing_policies,
        timeout_seconds=float(settings.timeout_seconds),
    )
    definitions = discover_dependencies(gateway, settings, routing=routing)
    with ThreadPoolExecutor(
        max_workers=settings.max_parallel_probes,
        thread_name_prefix="database-probe",
    ) as executor:
        futures = [
            executor.submit(
                _execute_one,
                gateway,
                definition,
                settings=settings,
                observed_at_ts=observed_at_ts,
            )
            for definition in definitions
        ]
        observations = [future.result() for future in futures]
    return reduce_state(
        definitions=definitions,
        observations=observations,
        previous=retained,
        settings=settings,
        generated_at_ts=time.time(),
    )


def _run_and_checkpoint(
    gateway: DockerGateway,
    retained: JsonObject,
    settings: DatabaseDependencySettings,
    *,
    state_path: Path,
    event_bus: DatabaseEventBus | None,
) -> tuple[JsonObject, DatabaseEventBus | None]:
    updated = _run_cycle(
        gateway,
        retained,
        settings,
        observed_at_ts=time.time(),
    )
    staged_event_bus = event_bus.staged_for_cycle(previous=retained, updated=updated) if event_bus is not None else None
    if staged_event_bus is not None:
        updated["event_bus_outbox"] = staged_event_bus.state_value()
    write_state(state_path, updated)
    LOGGER.info(
        "database dependency cycle complete dependencies=%d",
        len(object_list(updated.get("dependencies"))),
    )
    return updated, staged_event_bus


def _flush_event_bus(
    event_bus: DatabaseEventBus,
    retained: JsonObject,
    *,
    state_path: Path,
) -> None:
    event_bus.flush()
    retained["event_bus_outbox"] = event_bus.state_value()
    write_state(state_path, retained)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config_path = Path(os.getenv("DATABASE_DEPENDENCY_CONFIG_PATH", "domain_checks/config.yaml"))
    collector_settings = load_settings(config_path)
    configured_state_path = _configured_path(
        "DATABASE_DEPENDENCY_STATE_PATH",
        collector_settings.state_path,
    )
    try:
        retained_state = load_state(configured_state_path)
    except (OSError, TypeError, ValueError) as error:
        LOGGER.exception("database state load failed error_type=%s", type(error).__name__)
        retained_state = _collector_failure_state(
            {},
            collector_settings,
            error_class="retained_state_invalid",
            observed_at_ts=time.time(),
        )
        write_state(configured_state_path, retained_state)
    database_event_bus = DatabaseEventBus.from_state(retained_state)
    if database_event_bus is not None:
        LOGGER.info(
            "loaded database Events Bus outbox pending=%d",
            database_event_bus.pending_count,
        )
    docker_gateway = DockerGateway(
        socket_path=collector_settings.docker_socket_path,
        timeout_seconds=float(collector_settings.timeout_seconds + 4),
    )
    while True:
        cycle_started = time.monotonic()
        try:
            retained_state, database_event_bus = _run_and_checkpoint(
                docker_gateway,
                retained_state,
                collector_settings,
                state_path=configured_state_path,
                event_bus=database_event_bus,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            LOGGER.exception(
                "database dependency cycle failed error_type=%s",
                type(error).__name__,
            )
            retained_state = _collector_failure_state(
                retained_state,
                collector_settings,
                error_class="collector_cycle_failure",
                observed_at_ts=time.time(),
            )
            if database_event_bus is not None:
                retained_state["event_bus_outbox"] = database_event_bus.state_value()
            write_state(configured_state_path, retained_state)
        if database_event_bus is not None:
            try:
                _flush_event_bus(
                    database_event_bus,
                    retained_state,
                    state_path=configured_state_path,
                )
            except (HTTPError, OSError, RuntimeError, TypeError, ValueError):
                LOGGER.exception("database Events Bus flush/checkpoint failed")
        try:
            retained_state = deliver_pending_alerts(
                retained_state,
                state_path=configured_state_path,
            )
        except (
            DatabaseDependencyAlertConfigurationError,
            DatabaseDependencyAlertDeliveryError,
            HTTPError,
            OSError,
        ) as error:
            LOGGER.exception(
                "database alert delivery failed error_type=%s",
                type(error).__name__,
            )
            retained_state = _collector_failure_state(
                retained_state,
                collector_settings,
                error_class="telegram_alert_delivery_failure",
                observed_at_ts=time.time(),
            )
            if database_event_bus is not None:
                retained_state["event_bus_outbox"] = database_event_bus.state_value()
            write_state(configured_state_path, retained_state)
        elapsed = time.monotonic() - cycle_started
        time.sleep(max(1.0, collector_settings.interval_seconds - elapsed))
