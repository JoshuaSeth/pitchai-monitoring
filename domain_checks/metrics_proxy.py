from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain_checks.common_check import DomainCheckResult, DomainCheckSpec


@dataclass(frozen=True)
class ProxyIssue:
    domain: str
    ok: bool
    reason: str
    header: str | None
    value: str | None
    details: dict[str, Any]


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value if str(x or "").strip()]
    s = str(value or "").strip()
    return [s] if s else []


def check_upstream_header_expectations(
    *,
    specs_by_domain: dict[str, DomainCheckSpec],
    cycle_results: dict[str, DomainCheckResult],
) -> list[ProxyIssue]:
    issues: list[ProxyIssue] = []

    for domain, result in cycle_results.items():
        spec = specs_by_domain.get(domain)
        if spec is None:
            continue
        proxy_cfg = getattr(spec, "proxy", None)  # added dynamically in DomainCheckSpec
        if not isinstance(proxy_cfg, dict) or not proxy_cfg:
            continue

        header = str(proxy_cfg.get("upstream_header") or "x-aipc-upstream").strip().lower()
        primary = set(_as_str_list(proxy_cfg.get("primary_upstreams")))
        backup = set(_as_str_list(proxy_cfg.get("backup_upstreams")))
        alert_on_backup = bool(proxy_cfg.get("alert_on_backup", True))
        alert_on_missing = bool(proxy_cfg.get("alert_on_missing", False))
        alert_on_unknown = bool(proxy_cfg.get("alert_on_unknown", True))

        captured = (result.details or {}).get("captured_headers")
        captured = captured if isinstance(captured, dict) else {}
        value = captured.get(header)
        if value is None:
            if alert_on_missing:
                issues.append(
                    ProxyIssue(
                        domain=domain,
                        ok=False,
                        reason="missing_upstream_header",
                        header=header,
                        value=None,
                        details={"captured_headers": captured},
                    )
                )
            continue

        value_s = str(value).strip()
        if primary and value_s in primary:
            continue
        if backup and value_s in backup:
            if alert_on_backup:
                issues.append(
                    ProxyIssue(
                        domain=domain,
                        ok=False,
                        reason="backup_upstream_in_use",
                        header=header,
                        value=value_s,
                        details={"primary": sorted(primary), "backup": sorted(backup)},
                    )
                )
            continue

        if primary or backup:
            if alert_on_unknown:
                issues.append(
                    ProxyIssue(
                        domain=domain,
                        ok=False,
                        reason="unknown_upstream_value",
                        header=header,
                        value=value_s,
                        details={"primary": sorted(primary), "backup": sorted(backup)},
                    )
                )
            continue

    issues.sort(key=lambda x: x.domain)
    return issues

