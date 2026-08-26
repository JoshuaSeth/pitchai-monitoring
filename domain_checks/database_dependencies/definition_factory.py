# Copyright (c) 2026 PitchAI. All rights reserved.
"""Construct secret-free database dependency probe definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

from domain_checks.database_dependencies.models import (
    DatabaseDependencyInventoryError,
    ProbeDefinition,
)

if TYPE_CHECKING:
    from domain_checks.database_dependencies.models import (
        ConnectionMode,
        ProbeRule,
        TrafficState,
    )
    from domain_checks.database_dependencies.routing import RoutingResolution


@dataclass(frozen=True)
class ContainerDefinitionSource:
    """Secret-free live container context used to materialize definitions."""

    container_id: str
    container_name: str
    environment_names: set[str]
    routing: dict[str, RoutingResolution]


class _RouteState(NamedTuple):
    """Resolved production traffic state for one dependency slot."""

    traffic_state: TrafficState
    weight: int | None
    source: str
    error: str | None


def _credential_source(rule: ProbeRule, names: set[str]) -> str:
    if rule.connection_mode == "engine":
        return "application_engine"
    if any(key in names for key in rule.environment_keys):
        return "runtime_environment"
    if any(key in names for key in rule.file_environment_keys):
        return "runtime_credential_file"
    if rule.default_credential_path is not None:
        return "default_credential_file"
    if rule.default_sqlite_path is not None:
        return "default_sqlite_path"
    return "missing_runtime_credential"


def _coverage(rule: ProbeRule, *, mode: ConnectionMode) -> tuple[str, ...]:
    if mode == "sqlite":
        checks = [
            "database file reachable",
            "read-only query",
            "configured table permission",
        ]
    else:
        checks = ["login/authentication", "read-only query", "timeout/reachability"]
        if mode != "engine" or rule.schema_checks:
            checks.append("schema usage")
    if rule.schema_checks:
        checks.append("configured schema grants")
    if rule.relation_checks:
        checks.append("configured table/materialized-view grants")
    return tuple(dict.fromkeys(checks))


def _routing_state(
    rule: ProbeRule,
    routing: dict[str, RoutingResolution],
) -> _RouteState:
    if rule.routing_policy_id is None or rule.traffic_slot is None:
        return _RouteState("active", 100, "singleton", None)
    resolution = routing.get(rule.routing_policy_id)
    if resolution is None:
        return _RouteState("unknown", None, "configuration", "routing_policy_not_resolved")
    state, weight = resolution.slot_state(rule.traffic_slot)
    return _RouteState(state, weight, resolution.source_label, resolution.error_class)


def _alert_route(rule: ProbeRule, *, traffic_state: TrafficState) -> tuple[bool, str | None]:
    if not rule.telegram_enabled:
        return False, "dashboard_only_policy"
    if traffic_state == "unknown":
        return False, "routing_unknown"
    if traffic_state == "inactive":
        return False, "inactive_slot"
    return True, None


def build_definition(
    rule: ProbeRule,
    source: ContainerDefinitionSource,
    *,
    mode: ConnectionMode | None = None,
    environment_keys: tuple[str, ...] | None = None,
    id_suffix: str | None = None,
) -> ProbeDefinition:
    """Build one concrete database dependency definition.

    Returns:
        A secret-free probe definition for the live container path.
    """
    resolved_mode = mode or rule.connection_mode
    resolved_environment_keys = environment_keys if environment_keys is not None else rule.environment_keys
    route = _routing_state(rule, source.routing)
    telegram_route_eligible, suppression_reason = _alert_route(rule, traffic_state=route.traffic_state)
    dependency_id = f"{rule.rule_id}:{source.container_name}"
    if id_suffix:
        dependency_id = f"{dependency_id}:{id_suffix.lower()}"
    generic = rule.rule_id == "discovered-production"
    credential_source = (
        "runtime_environment"
        if generic and resolved_environment_keys
        else _credential_source(rule, source.environment_names)
    )
    return ProbeDefinition(
        dependency_id=dependency_id,
        dependency_kind="database",
        container_id=source.container_id,
        container_name=source.container_name,
        app_name=source.container_name if generic else rule.app_name,
        owner_project=rule.owner_project,
        environment=rule.environment,
        database_label=(resolved_environment_keys[0] if generic else rule.database_label),
        critical=rule.critical,
        telegram_policy_enabled=rule.telegram_enabled,
        domains=rule.domains,
        likely_fix_path=rule.likely_fix_path,
        mode=resolved_mode,
        environment_keys=resolved_environment_keys,
        file_environment_keys=rule.file_environment_keys,
        default_credential_path=rule.default_credential_path,
        default_sqlite_path=rule.default_sqlite_path,
        engine_attr=rule.engine_attr,
        engine_callable=rule.engine_callable,
        sync_driver=rule.sync_driver,
        relation_checks=rule.relation_checks,
        schema_checks=rule.schema_checks,
        coverage=_coverage(rule, mode=resolved_mode),
        credential_source=credential_source,
        routing_policy_id=rule.routing_policy_id,
        traffic_slot=rule.traffic_slot,
        traffic_state=route.traffic_state,
        traffic_weight=route.weight,
        routing_source=route.source,
        routing_error=route.error,
        alert_group=rule.alert_group,
        telegram_route_eligible=telegram_route_eligible,
        telegram_suppression_reason=suppression_reason,
    )


def build_coverage_gap(rule: ProbeRule) -> ProbeDefinition:
    """Represent a required app surface missing from the running inventory.

    Returns:
        A dashboard-only coverage-gap definition.

    Raises:
        DatabaseDependencyInventoryError: If the rule has no required group.
    """
    required_group = rule.required_group
    if required_group is None:
        message = "coverage gap requested for a rule without a required group"
        raise DatabaseDependencyInventoryError(message)
    return ProbeDefinition(
        dependency_id=f"coverage:{required_group}",
        dependency_kind="coverage_gap",
        container_id=None,
        container_name=f"No running container matched required group {required_group}",
        app_name=rule.app_name,
        owner_project=rule.owner_project,
        environment=rule.environment,
        database_label=rule.database_label,
        critical=False,
        telegram_policy_enabled=False,
        domains=rule.domains,
        likely_fix_path="Restore or rename the expected app container, then verify its database dependency policy.",
        mode=rule.connection_mode,
        environment_keys=(),
        file_environment_keys=(),
        default_credential_path=None,
        default_sqlite_path=None,
        engine_attr=None,
        engine_callable=False,
        sync_driver=None,
        relation_checks=(),
        schema_checks=(),
        coverage=("container inventory coverage",),
        credential_source="unavailable",
        routing_policy_id=rule.routing_policy_id,
        traffic_slot=rule.traffic_slot,
        traffic_state="unknown",
        traffic_weight=None,
        routing_source="inventory",
        routing_error="required_container_group_missing",
        alert_group=f"coverage:{required_group}",
        telegram_route_eligible=False,
        telegram_suppression_reason="coverage_gap_dashboard_only",
    )
