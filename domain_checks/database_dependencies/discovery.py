# Copyright (c) 2026 PitchAI. All rights reserved.
"""Discover database-backed production containers without retaining values."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from domain_checks.monitoring_contracts.json_types import text_value, value_list

from .definition_factory import (
    ContainerDefinitionSource,
    build_coverage_gap,
    build_definition,
)
from .models import DatabaseDependencyInventoryError

if TYPE_CHECKING:
    from domain_checks.monitoring_contracts.json_types import JsonObject

    from .models import (
        DatabaseDependencySettings,
        ProbeDefinition,
        ProbeRule,
    )
    from .routing import RoutingResolution


class DockerInventoryGateway(Protocol):
    """Read-only Docker inventory operations required by discovery."""

    def running_containers(self) -> list[JsonObject]:
        """List running container summaries."""
        raise NotImplementedError

    def inspect_container(self, container_id: str) -> JsonObject:
        """Inspect one container by exact id."""
        raise NotImplementedError


def _container_name(summary: JsonObject) -> str:
    for value in value_list(summary.get("Names")):
        name = text_value(value).removeprefix("/").strip()
        if name:
            return name
    message = "a running Docker container has no name"
    raise DatabaseDependencyInventoryError(message)


def _environment_names(inspect: JsonObject) -> set[str]:
    config = inspect.get("Config")
    if not isinstance(config, dict):
        message = "Docker inspection omitted Config"
        raise DatabaseDependencyInventoryError(message)
    names: set[str] = set()
    for raw in value_list(config.get("Env")):
        item = text_value(raw)
        key, separator, _value = item.partition("=")
        if separator and key:
            names.add(key)
    return names


def _matching_rule(name: str, rules: tuple[ProbeRule, ...]) -> ProbeRule:
    for rule in rules:
        if rule.container_pattern.search(name):
            return rule
    message = f"container {name} has no explicit database ownership policy"
    raise DatabaseDependencyInventoryError(message)


def _generic_environment_keys(
    names: set[str],
    settings: DatabaseDependencySettings,
) -> tuple[str, ...]:
    selected: list[str] = []
    for key in sorted(names):
        excluded = any(pattern.search(key) for pattern in settings.environment_key_exclude_patterns)
        matched = any(pattern.search(key) for pattern in settings.environment_key_patterns)
        if matched and not excluded:
            selected.append(key)
    return tuple(selected)


def _append_container_definitions(
    definitions: list[ProbeDefinition],
    *,
    rule: ProbeRule,
    source: ContainerDefinitionSource,
    settings: DatabaseDependencySettings,
) -> None:
    if rule.rule_id != "discovered-production":
        definitions.append(
            build_definition(
                rule,
                source,
            ),
        )
        return
    for key in _generic_environment_keys(source.environment_names, settings):
        mode = "sqlite" if key.endswith("_PATH") else "sqlalchemy_url"
        definitions.append(
            build_definition(
                rule,
                source,
                mode=mode,
                environment_keys=(key,),
                id_suffix=key,
            ),
        )


def discover_dependencies(
    gateway: DockerInventoryGateway,
    settings: DatabaseDependencySettings,
    *,
    routing: dict[str, RoutingResolution],
) -> list[ProbeDefinition]:
    """Resolve every running database-backed production app container.

    Returns:
        Sorted secret-free dependency definitions, including coverage gaps.

    Raises:
        DatabaseDependencyInventoryError: If the runtime inventory violates policy.
    """
    definitions: list[ProbeDefinition] = []
    matched_required_groups: set[str] = set()
    for summary in gateway.running_containers():
        name = _container_name(summary)
        if any(pattern.search(name) for pattern in settings.exclude_patterns):
            continue
        container_id = text_value(summary.get("Id")).strip()
        if not container_id:
            message = f"running container {name} has no Docker id"
            raise DatabaseDependencyInventoryError(message)
        rule = _matching_rule(name, settings.rules)
        names = _environment_names(gateway.inspect_container(container_id))
        source = ContainerDefinitionSource(
            container_id=container_id,
            container_name=name,
            environment_names=names,
            routing=routing,
        )
        if rule.required_group is not None:
            matched_required_groups.add(rule.required_group)
        _append_container_definitions(
            definitions,
            rule=rule,
            source=source,
            settings=settings,
        )
    required_rules: dict[str, ProbeRule] = {}
    for rule in reversed(settings.rules):
        if rule.required_group is not None:
            required_rules[rule.required_group] = rule
    for group, rule in required_rules.items():
        if group not in matched_required_groups:
            definitions.append(build_coverage_gap(rule))
    identifiers = [definition.dependency_id for definition in definitions]
    if len(identifiers) != len(set(identifiers)):
        message = "database dependency ids collided in the live inventory"
        raise DatabaseDependencyInventoryError(message)
    return sorted(
        definitions,
        key=lambda item: (
            item.owner_project.lower(),
            item.app_name.lower(),
            item.dependency_id,
        ),
    )
