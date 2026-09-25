# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict validation for the domain inventory contract."""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING

from domain_checks.inventory_policy import (
    parse_domain_alert_policy,
    required_inventory_text,
)

if TYPE_CHECKING:
    from domain_checks.types import JsonObject, JsonValue

_HOST_PATTERN = (
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
)
_HOST_RE = re.compile(_HOST_PATTERN)
_ENVIRONMENTS = {"production", "staging", "demo", "internal"}
_KINDS = {"application", "api", "alias", "auth", "infrastructure", "storage"}
_EXCLUSION_CLASSES = {
    "retired",
    "historical",
    "dns-only",
    "replaced",
    "non-http",
    "pending",
    "not-owned",
    "namespace",
    "invalid-alias",
}


def _validate_sources(value: JsonValue, path: str) -> list[str]:
    if not isinstance(value, list) or not value:
        message = f"{path}.sources must be a non-empty list"
        raise ValueError(message)
    sources: list[str] = []
    for item in value:
        source = str(item or "").strip()
        if not source:
            message = f"{path}.sources contains an empty value"
            raise ValueError(message)
        sources.append(source)
    return sources


def _validate_hostname(value: str, path: str) -> None:
    if value != value.lower() or _HOST_RE.fullmatch(value) is None:
        message = f"{path} must be a lowercase fully-qualified hostname: {value!r}"
        raise ValueError(message)


def _validate_inventory_metadata(config: JsonObject) -> None:
    inventory = config.get("inventory")
    if not isinstance(inventory, dict):
        message = "inventory must be a mapping"
        raise TypeError(message)
    version = inventory.get("version")
    if not isinstance(version, int) or version < 1:
        message = "inventory.version must be a positive integer"
        raise ValueError(message)
    reviewed_at = required_inventory_text(inventory, "reviewed_at", "inventory")
    try:
        _ = date.fromisoformat(reviewed_at)
    except ValueError as exc:
        message = "inventory.reviewed_at must be an ISO-8601 date"
        raise ValueError(message) from exc
    _ = _validate_sources(inventory.get("authoritative_sources"), "inventory")


def _validate_container_patterns(config: JsonObject) -> None:
    container_health = config.get("container_health")
    if not isinstance(container_health, dict):
        message = "container_health must be a mapping"
        raise TypeError(message)
    patterns = container_health.get("include_name_patterns")
    if not isinstance(patterns, list) or not patterns:
        message = "container_health.include_name_patterns must be a non-empty list"
        raise ValueError(message)
    for index, pattern in enumerate(patterns):
        cleaned_pattern = str(pattern or "").strip()
        if not cleaned_pattern:
            message = f"container_health.include_name_patterns[{index}] is empty"
            raise ValueError(message)
        try:
            _ = re.compile(cleaned_pattern)
        except re.error as exc:
            message = f"container_health.include_name_patterns[{index}] is invalid: {cleaned_pattern!r}"
            raise ValueError(message) from exc


def _validate_groups(config: JsonObject) -> JsonObject:
    groups = config.get("domain_groups")
    if not isinstance(groups, dict) or not groups:
        message = "domain_groups must be a non-empty mapping"
        raise ValueError(message)
    for group_id, raw_group in groups.items():
        path = f"domain_groups.{group_id}"
        if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", group_id) is None:
            message = f"invalid domain group id: {group_id!r}"
            raise ValueError(message)
        if not isinstance(raw_group, dict):
            message = f"{path} must be a mapping"
            raise TypeError(message)
        _ = required_inventory_text(raw_group, "label", path)
        _ = required_inventory_text(raw_group, "description", path)
        if not isinstance(raw_group.get("order"), int):
            message = f"{path}.order must be an integer"
            raise TypeError(message)
    return groups


def _validate_active_domain(
    raw_domain: JsonObject,
    path: str,
    groups: JsonObject,
    active: set[str],
) -> None:
    hostname = required_inventory_text(raw_domain, "domain", path)
    _validate_hostname(hostname, f"{path}.domain")
    if hostname in active:
        message = f"duplicate active domain: {hostname}"
        raise ValueError(message)
    active.add(hostname)
    _ = required_inventory_text(raw_domain, "label", path)
    group = required_inventory_text(raw_domain, "group", path)
    if group not in groups:
        message = f"{path}.group references unknown group {group!r}"
        raise ValueError(message)
    environment = required_inventory_text(raw_domain, "environment", path)
    if environment not in _ENVIRONMENTS:
        message = f"{path}.environment must be one of {sorted(_ENVIRONMENTS)}"
        raise ValueError(message)
    kind = required_inventory_text(raw_domain, "kind", path)
    if kind not in _KINDS:
        message = f"{path}.kind must be one of {sorted(_KINDS)}"
        raise ValueError(message)
    _ = _validate_sources(raw_domain.get("sources"), path)
    _ = parse_domain_alert_policy(raw_domain, path=path)
    if bool(raw_domain.get("disabled")) or raw_domain.get("enabled") is False:
        _ = required_inventory_text(raw_domain, "disabled_reason", path)


def _validate_active_domains(config: JsonObject, groups: JsonObject) -> set[str]:
    domains = config.get("domains")
    if not isinstance(domains, list) or not domains:
        message = "domains must be a non-empty list"
        raise ValueError(message)
    active: set[str] = set()
    for index, raw_domain in enumerate(domains):
        path = f"domains[{index}]"
        if not isinstance(raw_domain, dict):
            message = f"{path} must be a metadata mapping"
            raise TypeError(message)
        _validate_active_domain(raw_domain, path, groups, active)
    return active


def _validate_retired_domain(
    raw_domain: JsonObject,
    path: str,
    active: set[str],
    excluded: set[str],
) -> None:
    hostname = required_inventory_text(raw_domain, "domain", path)
    _validate_hostname(hostname, f"{path}.domain")
    if hostname in active:
        message = f"domain appears in active and retired inventory: {hostname}"
        raise ValueError(message)
    if hostname in excluded:
        message = f"duplicate retired domain: {hostname}"
        raise ValueError(message)
    excluded.add(hostname)
    classification = required_inventory_text(raw_domain, "classification", path)
    if classification not in _EXCLUSION_CLASSES:
        message = f"{path}.classification must be one of {sorted(_EXCLUSION_CLASSES)}"
        raise ValueError(message)
    _ = required_inventory_text(raw_domain, "reason", path)
    _ = _validate_sources(raw_domain.get("sources"), path)


def _validate_retired_domains(config: JsonObject, active: set[str]) -> None:
    retired = config.get("retired_domains")
    if not isinstance(retired, list):
        message = "retired_domains must be a list"
        raise TypeError(message)
    excluded: set[str] = set()
    for index, raw_domain in enumerate(retired):
        path = f"retired_domains[{index}]"
        if not isinstance(raw_domain, dict):
            message = f"{path} must be a mapping"
            raise TypeError(message)
        _validate_retired_domain(raw_domain, path, active, excluded)


def validate_domain_inventory(config: JsonObject) -> None:
    """Validate inventory metadata, active domains, and retired exclusions."""
    _validate_inventory_metadata(config)
    _validate_container_patterns(config)
    groups = _validate_groups(config)
    active = _validate_active_domains(config, groups)
    _validate_retired_domains(config, active)
