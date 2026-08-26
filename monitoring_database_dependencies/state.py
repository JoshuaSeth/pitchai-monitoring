# Copyright (c) 2026 PitchAI. All rights reserved.
"""Debounced, secret-free database dependency state and alert reduction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from monitoring_contracts.json_types import bool_value, int_value, json_object, object_list, text_value

from .state_dependency import build_dependency_state
from .state_groups import reduce_alert_groups

if TYPE_CHECKING:
    from monitoring_contracts.json_types import JsonObject

    from .models import (
        DatabaseDependencySettings,
        ProbeDefinition,
        ProbeObservation,
    )

_SUPPORTED_STATE_VERSIONS = {1, 2}
_CURRENT_STATE_VERSION = 2


class DatabaseDependencyStateError(RuntimeError):
    """Retained database dependency state is malformed or inconsistent."""


def _state_version(previous: JsonObject) -> int | None:
    if not previous:
        return None
    version = int_value(previous.get("version"))
    if version not in _SUPPORTED_STATE_VERSIONS:
        message = "database dependency state version is unsupported"
        raise DatabaseDependencyStateError(message)
    return version


def _index_by_text(
    items: list[JsonObject],
    *,
    key: str,
    description: str,
) -> dict[str, JsonObject]:
    indexed: dict[str, JsonObject] = {}
    for item in items:
        identifier = text_value(item.get(key))
        if not identifier or identifier in indexed:
            message = f"retained {description} ids are missing or duplicated"
            raise DatabaseDependencyStateError(message)
        indexed[identifier] = item
    return indexed


def _previous_by_id(previous: JsonObject) -> dict[str, JsonObject]:
    return _index_by_text(
        object_list(previous.get("dependencies")),
        key="dependency_id",
        description="database dependency",
    )


def _previous_groups(previous: JsonObject) -> dict[str, JsonObject]:
    return _index_by_text(
        object_list(previous.get("alert_groups")),
        key="alert_group",
        description="database alert group",
    )


def _prior_cycle(previous: JsonObject) -> tuple[dict[str, JsonObject], dict[str, JsonObject]]:
    prior_version = _state_version(previous)
    prior_dependencies = _previous_by_id(previous)
    prior_groups = _previous_groups(previous) if prior_version == _CURRENT_STATE_VERSION else {}
    return prior_dependencies, prior_groups


def _observations_by_id(
    definitions: list[ProbeDefinition],
    observations: list[ProbeObservation],
) -> dict[str, ProbeObservation]:
    observed = {item.dependency_id: item for item in observations}
    if len(observed) != len(observations):
        message = "one cycle produced duplicate database observations"
        raise DatabaseDependencyStateError(message)
    definition_ids = {definition.dependency_id for definition in definitions}
    if set(observed) != definition_ids:
        message = "database dependency definitions and observations differ"
        raise DatabaseDependencyStateError(message)
    return observed


def _dependency_states(
    definitions: list[ProbeDefinition],
    observed: dict[str, ProbeObservation],
    prior: dict[str, JsonObject],
    settings: DatabaseDependencySettings,
) -> list[JsonObject]:
    return [
        build_dependency_state(
            definition,
            observed[definition.dependency_id],
            prior.get(definition.dependency_id, {}),
            settings,
        )
        for definition in definitions
    ]


def _collector_counts(dependencies: list[JsonObject]) -> tuple[int, int]:
    alertable_down = sum(bool_value(item.get("telegram_alert_eligible")) is True for item in dependencies)
    critical_count = sum(bool_value(item.get("critical")) is True for item in dependencies)
    return alertable_down, critical_count


def _overall_status(dependencies: list[JsonObject], *, alertable_down: int) -> str:
    if alertable_down:
        return "down"
    if any(text_value(item.get("status")) != "healthy" for item in dependencies):
        return "degraded"
    return "healthy"


def reduce_state(
    *,
    definitions: list[ProbeDefinition],
    observations: list[ProbeObservation],
    previous: JsonObject,
    settings: DatabaseDependencySettings,
    generated_at_ts: float,
) -> JsonObject:
    """Apply debounce, routing, and group deduplication to one probe cycle.

    Returns:
        The compact state for the completed collector cycle.

    """
    prior, prior_groups = _prior_cycle(previous)
    observed = _observations_by_id(definitions, observations)
    dependencies = _dependency_states(definitions, observed, prior, settings)
    alert_groups, pending = reduce_alert_groups(
        dependencies=dependencies,
        prior_groups=prior_groups,
        prior_dependencies=prior,
        pending_alerts=object_list(previous.get("pending_alerts")),
        generated_at_ts=generated_at_ts,
    )
    alertable_down, critical_count = _collector_counts(dependencies)
    overall = _overall_status(dependencies, alertable_down=alertable_down)
    return json_object({
        "version": _CURRENT_STATE_VERSION,
        "generated_at_ts": generated_at_ts,
        "status": overall,
        "collector": {
            "status": "healthy",
            "last_successful_cycle_at_ts": generated_at_ts,
            "interval_seconds": settings.interval_seconds,
            "dependency_count": len(dependencies),
            "critical_count": critical_count,
            "alertable_down_count": alertable_down,
        },
        "dependencies": dependencies,
        "alert_groups": alert_groups,
        "pending_alerts": pending,
    })
