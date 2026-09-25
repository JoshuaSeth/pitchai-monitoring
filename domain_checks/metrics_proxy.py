# Copyright (c) 2026 PitchAI. All rights reserved.
"""Reverse-proxy upstream expectation checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from domain_checks.common_check import DomainCheckResult, DomainCheckSpec
    from domain_checks.types import JsonObject, JsonValue


@dataclass(frozen=True)
class ProxyIssue:
    """Represent one reverse-proxy upstream issue."""

    domain: str
    ok: bool
    reason: str
    header: str | None
    value: str | None
    details: JsonObject


class _ProxyPolicy(NamedTuple):
    header: str
    primary: set[str]
    backup: set[str]
    alert_on_backup: bool
    alert_on_missing: bool
    alert_on_unknown: bool


def _as_str_list(value: JsonValue) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _proxy_policy(spec: DomainCheckSpec) -> _ProxyPolicy | None:
    config = spec.proxy
    if not config:
        return None
    header = str(config.get("upstream_header") or "x-aipc-upstream").strip().lower()
    return _ProxyPolicy(
        header=header,
        primary=set(_as_str_list(config.get("primary_upstreams"))),
        backup=set(_as_str_list(config.get("backup_upstreams"))),
        alert_on_backup=bool(config.get("alert_on_backup", True)),
        alert_on_missing=bool(config.get("alert_on_missing", False)),
        alert_on_unknown=bool(config.get("alert_on_unknown", True)),
    )


def _upstream_details(policy: _ProxyPolicy) -> JsonObject:
    primary: list[JsonValue] = []
    primary.extend(sorted(policy.primary))
    backup: list[JsonValue] = []
    backup.extend(sorted(policy.backup))
    return {"primary": primary, "backup": backup}


def _captured_headers(result: DomainCheckResult) -> JsonObject:
    captured = result.details.get("captured_headers")
    return captured if isinstance(captured, dict) else {}


def _proxy_issue(
    domain: str,
    result: DomainCheckResult,
    policy: _ProxyPolicy,
) -> ProxyIssue | None:
    captured = _captured_headers(result)
    raw_value = captured.get(policy.header)
    if raw_value is None:
        return (
            ProxyIssue(
                domain=domain,
                ok=False,
                reason="missing_upstream_header",
                header=policy.header,
                value=None,
                details={"captured_headers": captured},
            )
            if policy.alert_on_missing
            else None
        )
    value = str(raw_value).strip()
    issue: ProxyIssue | None = None
    if policy.primary and value in policy.primary:
        pass
    elif policy.backup and value in policy.backup and policy.alert_on_backup:
        issue = ProxyIssue(
            domain=domain,
            ok=False,
            reason="backup_upstream_in_use",
            header=policy.header,
            value=value,
            details=_upstream_details(policy),
        )
    elif (policy.primary or policy.backup) and value not in policy.backup and policy.alert_on_unknown:
        issue = ProxyIssue(
            domain=domain,
            ok=False,
            reason="unknown_upstream_value",
            header=policy.header,
            value=value,
            details=_upstream_details(policy),
        )
    return issue


def check_upstream_header_expectations(
    *,
    specs_by_domain: dict[str, DomainCheckSpec],
    cycle_results: dict[str, DomainCheckResult],
) -> list[ProxyIssue]:
    """Check captured proxy headers against configured upstream sets.

    Returns:
        Proxy issues ordered by domain.
    """
    issues: list[ProxyIssue] = []
    for domain, result in cycle_results.items():
        spec = specs_by_domain.get(domain)
        if spec is None:
            continue
        policy = _proxy_policy(spec)
        if policy is None:
            continue
        issue = _proxy_issue(domain, result, policy)
        if issue is not None:
            issues.append(issue)
    issues.sort(key=lambda issue: issue.domain)
    return issues
