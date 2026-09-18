from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any


_HOST_RE = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
)
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
_TELEGRAM_ALERT_MODES = {"critical", "dashboard-only"}


@dataclass(frozen=True)
class DomainAlertPolicy:
    telegram: str
    reason: str | None = None

    @property
    def telegram_enabled(self) -> bool:
        return self.telegram == "critical"

    def to_dashboard_dict(self) -> dict[str, Any]:
        return {
            "telegram": self.telegram,
            "telegram_enabled": self.telegram_enabled,
            "reason": self.reason,
        }


def parse_domain_alert_policy(raw_domain: Any, *, path: str = "domain") -> DomainAlertPolicy:
    """Parse a domain's alert-routing contract.

    Missing policy remains critical for backwards compatibility at the config
    input boundary. Dashboard-only entries must state why they are non-alerting.
    """
    if not isinstance(raw_domain, dict) or raw_domain.get("alert_policy") is None:
        return DomainAlertPolicy(telegram="critical")

    raw_policy = raw_domain.get("alert_policy")
    policy_path = f"{path}.alert_policy"
    if not isinstance(raw_policy, dict):
        raise ValueError(f"{policy_path} must be a mapping")

    telegram = _required_text(raw_policy, "telegram", policy_path)
    if telegram not in _TELEGRAM_ALERT_MODES:
        raise ValueError(
            f"{policy_path}.telegram must be one of {sorted(_TELEGRAM_ALERT_MODES)}"
        )
    reason = str(raw_policy.get("reason") or "").strip() or None
    if telegram == "dashboard-only" and reason is None:
        raise ValueError(f"{policy_path}.reason is required for dashboard-only domains")
    return DomainAlertPolicy(telegram=telegram, reason=reason)


def _required_text(mapping: dict[str, Any], key: str, path: str) -> str:
    value = str(mapping.get(key) or "").strip()
    if not value:
        raise ValueError(f"{path}.{key} is required")
    return value


def _validate_sources(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{path}.sources must be a non-empty list")
    sources = [str(item or "").strip() for item in value]
    if any(not item for item in sources):
        raise ValueError(f"{path}.sources contains an empty value")
    return sources


def _validate_hostname(value: str, path: str) -> None:
    if value != value.lower() or not _HOST_RE.fullmatch(value):
        raise ValueError(f"{path} must be a lowercase fully-qualified hostname: {value!r}")


def validate_domain_inventory(config: dict[str, Any]) -> None:
    inventory = config.get("inventory")
    if not isinstance(inventory, dict):
        raise ValueError("inventory must be a mapping")
    version = inventory.get("version")
    if not isinstance(version, int) or version < 1:
        raise ValueError("inventory.version must be a positive integer")
    reviewed_at = _required_text(inventory, "reviewed_at", "inventory")
    try:
        date.fromisoformat(reviewed_at)
    except ValueError as exc:
        raise ValueError("inventory.reviewed_at must be an ISO-8601 date") from exc
    _validate_sources(inventory.get("authoritative_sources"), "inventory")

    container_health = config.get("container_health")
    if not isinstance(container_health, dict):
        raise ValueError("container_health must be a mapping")
    include_patterns = container_health.get("include_name_patterns")
    if not isinstance(include_patterns, list) or not include_patterns:
        raise ValueError("container_health.include_name_patterns must be a non-empty list")
    for index, pattern in enumerate(include_patterns):
        cleaned_pattern = str(pattern or "").strip()
        if not cleaned_pattern:
            raise ValueError(f"container_health.include_name_patterns[{index}] is empty")
        try:
            re.compile(cleaned_pattern)
        except re.error as exc:
            raise ValueError(
                f"container_health.include_name_patterns[{index}] is invalid: {cleaned_pattern!r}"
            ) from exc

    groups = config.get("domain_groups")
    if not isinstance(groups, dict) or not groups:
        raise ValueError("domain_groups must be a non-empty mapping")
    for group_id, raw_group in groups.items():
        path = f"domain_groups.{group_id}"
        if not isinstance(group_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", group_id):
            raise ValueError(f"invalid domain group id: {group_id!r}")
        if not isinstance(raw_group, dict):
            raise ValueError(f"{path} must be a mapping")
        _required_text(raw_group, "label", path)
        _required_text(raw_group, "description", path)
        if not isinstance(raw_group.get("order"), int):
            raise ValueError(f"{path}.order must be an integer")

    domains = config.get("domains")
    if not isinstance(domains, list) or not domains:
        raise ValueError("domains must be a non-empty list")
    active: set[str] = set()
    for index, raw_domain in enumerate(domains):
        path = f"domains[{index}]"
        if not isinstance(raw_domain, dict):
            raise ValueError(f"{path} must be a metadata mapping")
        hostname = _required_text(raw_domain, "domain", path)
        _validate_hostname(hostname, f"{path}.domain")
        if hostname in active:
            raise ValueError(f"duplicate active domain: {hostname}")
        active.add(hostname)
        _required_text(raw_domain, "label", path)
        group = _required_text(raw_domain, "group", path)
        if group not in groups:
            raise ValueError(f"{path}.group references unknown group {group!r}")
        environment = _required_text(raw_domain, "environment", path)
        if environment not in _ENVIRONMENTS:
            raise ValueError(f"{path}.environment must be one of {sorted(_ENVIRONMENTS)}")
        kind = _required_text(raw_domain, "kind", path)
        if kind not in _KINDS:
            raise ValueError(f"{path}.kind must be one of {sorted(_KINDS)}")
        _validate_sources(raw_domain.get("sources"), path)
        parse_domain_alert_policy(raw_domain, path=path)
        if bool(raw_domain.get("disabled")) or raw_domain.get("enabled") is False:
            _required_text(raw_domain, "disabled_reason", path)

    retired = config.get("retired_domains")
    if not isinstance(retired, list):
        raise ValueError("retired_domains must be a list")
    excluded: set[str] = set()
    for index, raw_domain in enumerate(retired):
        path = f"retired_domains[{index}]"
        if not isinstance(raw_domain, dict):
            raise ValueError(f"{path} must be a mapping")
        hostname = _required_text(raw_domain, "domain", path)
        _validate_hostname(hostname, f"{path}.domain")
        if hostname in active:
            raise ValueError(f"domain appears in active and retired inventory: {hostname}")
        if hostname in excluded:
            raise ValueError(f"duplicate retired domain: {hostname}")
        excluded.add(hostname)
        classification = _required_text(raw_domain, "classification", path)
        if classification not in _EXCLUSION_CLASSES:
            raise ValueError(f"{path}.classification must be one of {sorted(_EXCLUSION_CLASSES)}")
        _required_text(raw_domain, "reason", path)
        _validate_sources(raw_domain.get("sources"), path)
