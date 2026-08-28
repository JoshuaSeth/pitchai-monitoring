# Copyright (c) 2026 PitchAI. All rights reserved.
"""Resolve domain incident routing from the canonical monitored inventory."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .domain_event_models import DomainIncidentPolicy
from .domain_runtime import load_domain_spec
from .json_types import (
    bool_value,
    object_list,
    optional_object,
    text_value,
    value_list,
)
from .safe_evidence import safe_public_url, safe_text_excerpt

if TYPE_CHECKING:
    from .json_types import JsonObject

_FALLBACK_PROJECT = "pitchai_monitoring"
_PROJECT_PATTERN = re.compile(r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$")


def domain_incident_policies(config: JsonObject) -> dict[str, DomainIncidentPolicy]:
    """Return explicit incident policy for every active inventory entry.

    Returns:
        Policies keyed by exact canonical hostname.

    Raises:
        ValueError: If canonical inventory metadata is incomplete or duplicated.
    """
    groups = optional_object(config.get("domain_groups"))
    policies: dict[str, DomainIncidentPolicy] = {}
    for entry in object_list(config.get("domains")):
        policy = _domain_policy(entry, groups=groups)
        if policy.domain in policies:
            message = f"duplicate domain incident policy: {policy.domain}"
            raise ValueError(message)
        policies[policy.domain] = policy
    return policies


def _domain_policy(entry: JsonObject, *, groups: JsonObject) -> DomainIncidentPolicy:
    specification = load_domain_spec(entry)
    domain = text_value(entry.get("domain"))
    group = text_value(entry.get("group"))
    group_metadata = optional_object(groups.get(group))
    alert_policy = optional_object(entry.get("alert_policy"))
    source_url = safe_public_url(specification.url)
    if not domain or not group or source_url is None:
        message = "domain incident policy requires a domain, group, and public check URL"
        raise ValueError(message)
    allowed_status_codes = tuple(specification.allowed_status_codes or (200,))
    owner_project = _owner_project(entry=entry, group=group_metadata)
    explicitly_disabled = bool_value(entry.get("disabled")) is True
    explicitly_enabled = bool_value(entry.get("enabled"))
    disabled = explicitly_disabled or explicitly_enabled is False
    return DomainIncidentPolicy(
        domain=domain,
        label=text_value(entry.get("label"), default=domain),
        group=group,
        group_label=text_value(group_metadata.get("label"), default=group),
        environment=text_value(entry.get("environment"), default="unspecified"),
        surface_kind=text_value(entry.get("kind"), default="application"),
        owner_project=owner_project,
        source_url=source_url,
        allowed_status_codes=allowed_status_codes,
        expected_final_host_suffix=specification.expected_final_host_suffix,
        expected_final_path=specification.expected_final_path,
        expected_title_contains=specification.expected_title_contains,
        alert_mode=text_value(alert_policy.get("telegram"), default="critical"),
        alert_reason=safe_text_excerpt(alert_policy.get("reason"), max_chars=300),
        disabled=disabled,
        sources=_sources(entry),
    )


def _owner_project(*, entry: JsonObject, group: JsonObject) -> str:
    requested = text_value(entry.get("owner_project")) or text_value(group.get("owner_project"))
    return requested if _PROJECT_PATTERN.fullmatch(requested) is not None else _FALLBACK_PROJECT


def _sources(entry: JsonObject) -> tuple[str, ...]:
    raw_sources = value_list(entry.get("sources"))
    string_sources = (item for item in raw_sources if isinstance(item, str))
    text_sources = (text_value(item).strip() for item in string_sources)
    present_sources = (source for source in text_sources if source)
    return tuple(present_sources)
