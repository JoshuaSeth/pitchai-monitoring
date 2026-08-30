# Copyright (c) 2026 PitchAI. All rights reserved.
"""Evaluate domain-scoped reverse-proxy response headers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from .production_signal_scope import production_signal_includes

if TYPE_CHECKING:
    from .common_check import DomainCheckResult, DomainCheckSpec

type _ProxyConfigValue = str | bool | list[str]
type _ProxyIssueDetailValue = str | list[str] | dict[str, str]


@dataclass(frozen=True)
class ProxyIssue:
    """One unexpected upstream response-header observation."""

    domain: str
    ok: bool
    reason: str
    header: str | None
    value: str | None
    details: dict[str, _ProxyIssueDetailValue]


@dataclass(frozen=True)
class _ProxyPolicy:
    header: str
    primary: frozenset[str]
    backup: frozenset[str]
    alert_on_backup: bool
    alert_on_missing: bool
    alert_on_unknown: bool


def _string_set(value: _ProxyConfigValue | None) -> frozenset[str]:
    if isinstance(value, list):
        normalized_items = (item.strip() for item in value)
        nonempty_items = (item for item in normalized_items if item)
        return frozenset(nonempty_items)
    normalized = value.strip() if isinstance(value, str) else ""
    return frozenset({normalized}) if normalized else frozenset()


def _proxy_policy(spec: DomainCheckSpec) -> _ProxyPolicy | None:
    proxy = cast("Mapping[str, _ProxyConfigValue]", cast("object", spec.proxy))
    if not proxy:
        return None
    return _ProxyPolicy(
        header=str(proxy.get("upstream_header") or "x-aipc-upstream").strip().lower(),
        primary=_string_set(proxy.get("primary_upstreams")),
        backup=_string_set(proxy.get("backup_upstreams")),
        alert_on_backup=bool(proxy.get("alert_on_backup", True)),
        alert_on_missing=bool(proxy.get("alert_on_missing", False)),
        alert_on_unknown=bool(proxy.get("alert_on_unknown", True)),
    )


def _captured_headers(result: DomainCheckResult) -> dict[str, str]:
    details = cast("Mapping[str, object]", cast("object", result.details))
    captured_value = details.get("captured_headers")
    if not isinstance(captured_value, Mapping):
        return {}
    captured_mapping = cast("Mapping[object, object]", captured_value)
    return {
        key: value
        for key, value in captured_mapping.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def _proxy_issue(
    *,
    domain: str,
    reason: str,
    policy: _ProxyPolicy,
    value: str | None,
    details: dict[str, _ProxyIssueDetailValue],
) -> ProxyIssue:
    return ProxyIssue(
        domain=domain,
        ok=False,
        reason=reason,
        header=policy.header,
        value=value,
        details=details,
    )


def _evaluate_result(domain: str, result: DomainCheckResult, policy: _ProxyPolicy) -> ProxyIssue | None:
    captured = _captured_headers(result)
    raw_value = captured.get(policy.header)
    if raw_value is None:
        if policy.alert_on_missing:
            return _proxy_issue(
                domain=domain,
                reason="missing_upstream_header",
                policy=policy,
                value=None,
                details={"captured_headers": captured},
            )
        return None

    value = str(raw_value).strip()
    if policy.primary and value in policy.primary:
        return None
    upstreams: dict[str, _ProxyIssueDetailValue] = {
        "primary": sorted(policy.primary),
        "backup": sorted(policy.backup),
    }
    if policy.backup and value in policy.backup:
        if policy.alert_on_backup:
            return _proxy_issue(
                domain=domain,
                reason="backup_upstream_in_use",
                policy=policy,
                value=value,
                details=upstreams,
            )
        return None
    issue = None
    if (policy.primary or policy.backup) and policy.alert_on_unknown:
        issue = _proxy_issue(
            domain=domain,
            reason="unknown_upstream_value",
            policy=policy,
            value=value,
            details=upstreams,
        )
    return issue


def check_upstream_header_expectations(
    *,
    specs_by_domain: dict[str, DomainCheckSpec],
    cycle_results: dict[str, DomainCheckResult],
) -> list[ProxyIssue]:
    """Return production-scoped upstream response-header issues.

    Unknown domains stay included, while known non-production and dashboard-only
    inventory entries cannot degrade the global production signal.

    Returns:
        Sorted production-scoped proxy issues.
    """
    issues: list[ProxyIssue] = []
    for domain, result in cycle_results.items():
        spec = specs_by_domain.get(domain)
        if spec is None or not production_signal_includes(domain):
            continue
        policy = _proxy_policy(spec)
        if policy is None:
            continue
        issue = _evaluate_result(domain, result, policy)
        if issue is not None:
            issues.append(issue)
    issues.sort(key=lambda issue: issue.domain)
    return issues
