# Copyright (c) 2026 PitchAI. All rights reserved.
"""Fail-closed configuration parsing for database dependency checks."""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING, cast

from .json_types import (
    json_object,
    object_list,
)
from .models import (
    DatabaseDependencySettings,
    RoutingPolicy,
)
from .rule_configuration import (
    DatabaseDependencyConfigurationError,
    optional_text,
    parse_probe_rule,
    required_boolean,
    required_positive_integer,
    required_text,
    text_tuple,
)
from .serialization_runtime import load_yaml

if TYPE_CHECKING:
    from pathlib import Path

    from .json_types import JsonInput, JsonObject, JsonValue
    from .models import ProbeRule, RoutingKind

_ROUTING_KINDS = {"http_header", "nginx_upstream_file"}
_MAX_PARALLEL_PROBES = 4


def _routing_kind(value: JsonValue | object, *, field: str) -> RoutingKind:
    kind = required_text(value, field=field)
    if kind not in _ROUTING_KINDS:
        message = f"database dependency setting {field} has unsupported kind {kind}"
        raise DatabaseDependencyConfigurationError(message)
    return cast("RoutingKind", kind)


def _slot_ports(
    value: JsonValue | object,
    *,
    field: str,
) -> tuple[tuple[str, int], ...]:
    raw = json_object(cast("JsonInput", value))
    ports: list[tuple[str, int]] = []
    for slot, port_value in raw.items():
        port = required_positive_integer(port_value, field=f"{field}.{slot}")
        ports.append((required_text(slot, field=f"{field}.slot"), port))
    return tuple(sorted(ports))


def _parse_routing_policy(raw: JsonObject, *, index: int) -> RoutingPolicy:
    prefix = f"database_dependencies.routing_policies[{index}]"
    kind = _routing_kind(raw.get("kind"), field=f"{prefix}.kind")
    header_name = optional_text(raw.get("header_name"))
    slot_ports = (
        _slot_ports(raw.get("slot_ports"), field=f"{prefix}.slot_ports") if kind == "nginx_upstream_file" else ()
    )
    if kind == "http_header" and header_name is None:
        message = f"{prefix}.header_name is required for http_header routing"
        raise DatabaseDependencyConfigurationError(message)
    if kind == "nginx_upstream_file" and not slot_ports:
        message = f"{prefix}.slot_ports is required for nginx_upstream_file routing"
        raise DatabaseDependencyConfigurationError(message)
    slots = text_tuple(raw.get("slots"), field=f"{prefix}.slots")
    if not slots or len(slots) != len(set(slots)):
        message = f"{prefix}.slots must contain unique slot names"
        raise DatabaseDependencyConfigurationError(message)
    if slot_ports and {slot for slot, _port in slot_ports} != set(slots):
        message = f"{prefix}.slot_ports must map every configured slot exactly once"
        raise DatabaseDependencyConfigurationError(message)
    return RoutingPolicy(
        policy_id=required_text(raw.get("id"), field=f"{prefix}.id"),
        kind=kind,
        source=required_text(raw.get("source"), field=f"{prefix}.source"),
        slots=slots,
        header_name=header_name,
        slot_ports=slot_ports,
    )


def _validate_policy_references(
    rules: tuple[ProbeRule, ...],
    policies: tuple[RoutingPolicy, ...],
) -> None:
    policies_by_id = {policy.policy_id: policy for policy in policies}
    if len(policies_by_id) != len(policies):
        message = "database dependency routing policy ids must be unique"
        raise DatabaseDependencyConfigurationError(message)
    for rule in rules:
        if rule.routing_policy_id is None:
            continue
        policy = policies_by_id.get(rule.routing_policy_id)
        if policy is None:
            message = f"database dependency rule {rule.rule_id} references an unknown routing policy"
            raise DatabaseDependencyConfigurationError(message)
        if rule.traffic_slot not in policy.slots:
            message = f"database dependency rule {rule.rule_id} references an unknown routing slot"
            raise DatabaseDependencyConfigurationError(message)


def _validate_rules(
    rules: tuple[ProbeRule, ...],
    policies: tuple[RoutingPolicy, ...],
) -> None:
    identifiers = [rule.rule_id for rule in rules]
    if len(identifiers) != len(set(identifiers)):
        message = "database dependency rule ids must be unique"
        raise DatabaseDependencyConfigurationError(message)
    if not rules or rules[-1].container_pattern.pattern != ".*":
        message = "database dependency rules must end with an explicit .* ownership policy"
        raise DatabaseDependencyConfigurationError(message)
    rules_with_required_group = (rule for rule in rules if rule.required_group is not None)
    required_groups = [cast("str", rule.required_group) for rule in rules_with_required_group]
    if len(required_groups) != len(set(required_groups)):
        group_counts = Counter(required_groups)
        group_count_pairs = group_counts.items()
        duplicate_group_pairs = (item for item in group_count_pairs if item[1] > 1)
        grouped_rules = {group for group, _count in duplicate_group_pairs}
        for group in grouped_rules:
            group_rules = [rule for rule in rules if rule.required_group == group]
            group_app_names = {rule.app_name for rule in group_rules}
            if len(group_app_names) != 1:
                message = f"required group {group} must describe one app surface"
                raise DatabaseDependencyConfigurationError(message)
    _validate_policy_references(rules, policies)


def _compiled_patterns(
    section: JsonObject,
    *,
    key: str,
    field: str,
) -> tuple[re.Pattern[str], ...]:
    """Compile one validated pattern tuple from the configuration section.

    Returns:
        The compiled regular expressions in declared order.
    """
    raw_patterns = text_tuple(section.get(key), field=field)
    compiled = [re.compile(raw_pattern) for raw_pattern in raw_patterns]
    return tuple(compiled)


def load_settings(path: Path) -> DatabaseDependencySettings:
    """Load the collector settings from the canonical monitoring config.

    Returns:
        Fully validated collector settings.

    Raises:
        DatabaseDependencyConfigurationError: If the monitoring policy is invalid.
    """
    decoded = load_yaml(path.read_text(encoding="utf-8"))
    root = json_object(decoded)
    section = json_object(root.get("database_dependencies"))
    if required_boolean(section.get("enabled"), field="database_dependencies.enabled") is not True:
        message = "database_dependencies.enabled must be true"
        raise DatabaseDependencyConfigurationError(message)
    policies_list: list[RoutingPolicy] = []
    for index, raw in enumerate(object_list(section.get("routing_policies"))):
        policies_list.append(_parse_routing_policy(raw, index=index))
    policies = tuple(policies_list)
    rules_list: list[ProbeRule] = []
    for index, raw in enumerate(object_list(section.get("rules"))):
        rules_list.append(parse_probe_rule(raw, index=index))
    rules = tuple(rules_list)
    _validate_rules(rules, policies)
    max_parallel_probes = required_positive_integer(
        section.get("max_parallel_probes"),
        field="max_parallel_probes",
    )
    if max_parallel_probes > _MAX_PARALLEL_PROBES:
        message = "database dependency max_parallel_probes must not exceed 4"
        raise DatabaseDependencyConfigurationError(message)
    return DatabaseDependencySettings(
        interval_seconds=required_positive_integer(
            section.get("interval_seconds"),
            field="interval_seconds",
        ),
        timeout_seconds=required_positive_integer(
            section.get("timeout_seconds"),
            field="timeout_seconds",
        ),
        down_after_failures=required_positive_integer(
            section.get("down_after_failures"),
            field="down_after_failures",
        ),
        up_after_successes=required_positive_integer(
            section.get("up_after_successes"),
            field="up_after_successes",
        ),
        max_parallel_probes=max_parallel_probes,
        docker_socket_path=required_text(
            section.get("docker_socket_path"),
            field="docker_socket_path",
        ),
        state_path=required_text(section.get("state_path"), field="state_path"),
        python_executable=required_text(
            section.get("python_executable"),
            field="python_executable",
        ),
        environment_key_patterns=_compiled_patterns(
            section,
            key="environment_key_patterns",
            field="environment_key_patterns",
        ),
        environment_key_exclude_patterns=_compiled_patterns(
            section,
            key="environment_key_exclude_patterns",
            field="environment_key_exclude_patterns",
        ),
        exclude_patterns=_compiled_patterns(
            section,
            key="exclude_name_patterns",
            field="exclude_name_patterns",
        ),
        routing_policies=policies,
        rules=rules,
    )
