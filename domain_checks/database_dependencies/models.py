# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed contracts for production database dependency monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NamedTuple

if TYPE_CHECKING:
    from re import Pattern

    from domain_checks.monitoring_contracts.json_types import JsonObject

ConnectionMode = Literal["engine", "sqlalchemy_url", "psycopg_url", "asyncpg_url", "sqlite"]
DependencyKind = Literal["database", "coverage_gap"]
RoutingKind = Literal["http_header", "nginx_upstream_file"]
TrafficState = Literal["active", "inactive", "unknown"]


class DatabaseDependencyInventoryError(RuntimeError):
    """The live dependency inventory violates its explicit policy."""


@dataclass(frozen=True)
class RoutingPolicy:
    """One bounded source of production blue/green traffic truth."""

    policy_id: str
    kind: RoutingKind
    source: str
    slots: tuple[str, ...]
    header_name: str | None
    slot_ports: tuple[tuple[str, int], ...]


class ProbeRule(NamedTuple):
    """One ordered container-to-database monitoring policy."""

    rule_id: str
    container_pattern: Pattern[str]
    app_name: str
    owner_project: str
    database_label: str
    environment: str
    critical: bool
    telegram_enabled: bool
    required_group: str | None
    domains: tuple[str, ...]
    likely_fix_path: str
    connection_mode: ConnectionMode
    environment_keys: tuple[str, ...]
    file_environment_keys: tuple[str, ...]
    default_credential_path: str | None
    default_sqlite_path: str | None
    engine_attr: str | None
    engine_callable: bool
    sync_driver: str | None
    relation_checks: tuple[str, ...]
    schema_checks: tuple[str, ...]
    routing_policy_id: str | None
    traffic_slot: str | None
    alert_group: str


class DatabaseDependencySettings(NamedTuple):
    """Validated collector configuration."""

    interval_seconds: int
    timeout_seconds: int
    down_after_failures: int
    up_after_successes: int
    max_parallel_probes: int
    docker_socket_path: str
    state_path: str
    python_executable: str
    environment_key_patterns: tuple[Pattern[str], ...]
    environment_key_exclude_patterns: tuple[Pattern[str], ...]
    exclude_patterns: tuple[Pattern[str], ...]
    routing_policies: tuple[RoutingPolicy, ...]
    rules: tuple[ProbeRule, ...]


class ProbeDefinition(NamedTuple):
    """One concrete app-container database path to check."""

    dependency_id: str
    dependency_kind: DependencyKind
    container_id: str | None
    container_name: str
    app_name: str
    owner_project: str
    environment: str
    database_label: str
    critical: bool
    telegram_policy_enabled: bool
    domains: tuple[str, ...]
    likely_fix_path: str
    mode: ConnectionMode
    environment_keys: tuple[str, ...]
    file_environment_keys: tuple[str, ...]
    default_credential_path: str | None
    default_sqlite_path: str | None
    engine_attr: str | None
    engine_callable: bool
    sync_driver: str | None
    relation_checks: tuple[str, ...]
    schema_checks: tuple[str, ...]
    coverage: tuple[str, ...]
    credential_source: str
    routing_policy_id: str | None
    traffic_slot: str | None
    traffic_state: TrafficState
    traffic_weight: int | None
    routing_source: str
    routing_error: str | None
    alert_group: str
    telegram_route_eligible: bool
    telegram_suppression_reason: str | None


@dataclass(frozen=True)
class ProbeExecution:
    """Raw Docker-exec result with strictly bounded output."""

    exit_code: int | None
    stdout: bytes
    stderr: bytes
    boundary_failure: str | None


class ProbeObservation(NamedTuple):
    """Sanitized result used by state and alert policy."""

    dependency_id: str
    observed_at_ts: float
    ok: bool
    latency_ms: float | None
    failure_class: str | None
    failure_phase: str | None
    sqlstate: str | None
    sanitized_error_excerpt: str | None


def definition_contract(definition: ProbeDefinition) -> JsonObject:
    """Return the non-secret dashboard contract for one dependency."""
    return {
        "dependency_id": definition.dependency_id,
        "dependency_kind": definition.dependency_kind,
        "container": definition.container_name,
        "affected_app": definition.app_name,
        "owner_project": definition.owner_project,
        "environment": definition.environment,
        "database_dependency": definition.database_label,
        "critical": definition.critical,
        "telegram_policy_enabled": definition.telegram_policy_enabled,
        "domains": list(definition.domains),
        "likely_fix_path": definition.likely_fix_path,
        "coverage": list(definition.coverage),
        "credential_source": definition.credential_source,
        "routing_policy_id": definition.routing_policy_id,
        "traffic_slot": definition.traffic_slot,
        "traffic_state": definition.traffic_state,
        "traffic_weight": definition.traffic_weight,
        "routing_source": definition.routing_source,
        "routing_error": definition.routing_error,
        "alert_group": definition.alert_group,
        "telegram_route_eligible": definition.telegram_route_eligible,
        "telegram_suppression_reason": definition.telegram_suppression_reason,
    }
