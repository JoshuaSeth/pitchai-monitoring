# Copyright (c) 2026 PitchAI. All rights reserved.
"""Apply existing configured upstream-header expectations to domain results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .common_check import DomainCheckResult, DomainCheckSpec
    from .event_bus_delivery import JsonObject, JsonValue


@dataclass(frozen=True)
class ProxyIssue:
    """One existing header failure with its JSON diagnostic fields."""

    domain: str
    ok: bool
    reason: str
    header: str | None
    value: str | None
    details: JsonObject


def _as_str_list(value: JsonValue) -> list[str]:
    """Normalize existing JSON settings without changing list item whitespace.

    Returns:
        Nonempty string forms in their configured order.
    """
    if value is None:
        return []
    if isinstance(value, list):
        nonempty = [item for item in value if str(item or "").strip()]
        return [str(item) for item in nonempty]
    s = str(value or "").strip()
    return [s] if s else []


def check_upstream_header_expectations(
    *,
    specs_by_domain: dict[str, DomainCheckSpec],
    cycle_results: dict[str, DomainCheckResult],
) -> list[ProxyIssue]:
    """Compare captured headers with the original primary/backup policy.

    Returns:
        Failures sorted by domain; caller-owned settings and results are unchanged.
    """
    issues: list[ProxyIssue] = []

    for domain, result in cycle_results.items():
        spec = specs_by_domain.get(domain)
        if spec is None:
            continue
        proxy_cfg = cast("JsonValue", spec.proxy)
        if not isinstance(proxy_cfg, dict) or not proxy_cfg:
            continue

        header = str(proxy_cfg.get("upstream_header") or "x-aipc-upstream").strip().lower()
        primary = set(_as_str_list(proxy_cfg.get("primary_upstreams")))
        backup = set(_as_str_list(proxy_cfg.get("backup_upstreams")))

        details = cast("JsonObject", result.details)
        captured = (details or {}).get("captured_headers")
        captured = captured if isinstance(captured, dict) else {}
        value = captured.get(header)
        if value is None:
            if bool(proxy_cfg.get("alert_on_missing", False)):
                issues.append(
                    ProxyIssue(
                        domain=domain,
                        ok=False,
                        reason="missing_upstream_header",
                        header=header,
                        value=None,
                        details={"captured_headers": captured},
                    ),
                )
            continue

        value_s = str(value).strip()
        if primary and value_s in primary:
            continue
        if backup and value_s in backup:
            if bool(proxy_cfg.get("alert_on_backup", True)):
                issues.append(
                    ProxyIssue(
                        domain=domain,
                        ok=False,
                        reason="backup_upstream_in_use",
                        header=header,
                        value=value_s,
                        details={"primary": cast("JsonValue", sorted(primary)),
                                 "backup": cast("JsonValue", sorted(backup))},
                    ),
                )
            continue

        if primary or backup:
            if bool(proxy_cfg.get("alert_on_unknown", True)):
                issues.append(
                    ProxyIssue(
                        domain=domain,
                        ok=False,
                        reason="unknown_upstream_value",
                        header=header,
                        value=value_s,
                        details={"primary": cast("JsonValue", sorted(primary)),
                                 "backup": cast("JsonValue", sorted(backup))},
                    ),
                )
            continue

    issues.sort(key=lambda x: x.domain)
    return issues
