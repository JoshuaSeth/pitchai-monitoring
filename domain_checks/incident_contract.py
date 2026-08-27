"""Stable critical-incident metadata for monitored production domains."""

from __future__ import annotations

import hashlib
import json

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

_DASHBOARD_URL = "https://monitoring.pitchai.net/dashboard#domains-title"
_MAX_ERROR_CHARS = 800
_MAX_EVIDENCE_ITEMS = 12


def domain_down_details(  # noqa: PLR0913
    *,
    domain: str,
    raw_entry: JsonObject | str,
    routes_telegram: bool,
    alert_policy: str,
    disabled: bool,
    reason: str,
    check_details: JsonObject,
    fail_streak: int,
) -> JsonObject:
    """Build actionable, material-only metadata for one DOWN transition.

    Returns:
        A strict-JSON details object shared by alert routing and incident dispatch.
    """
    inventory = _mapping(raw_entry)
    target_environment = _text(inventory.get("environment")) or "production"
    critical = bool(routes_telegram and target_environment == "production" and not disabled)
    error = _bounded_text(check_details.get("error"), limit=_MAX_ERROR_CHARS)
    status_code = _integer(check_details.get("status_code"))
    final_url = _bounded_text(check_details.get("final_url"), limit=500)
    fingerprint = _fingerprint(
        {
            "domain": domain.lower(),
            "error": error,
            "final_url": final_url,
            "reason": reason,
            "status_code": status_code,
        },
    )
    details = _base_domain_details(
        domain=domain,
        inventory=inventory,
        critical=critical,
        target_environment=target_environment,
        fingerprint=fingerprint,
    )
    details.update(
        {
            "telegram_alert": routes_telegram,
            "alert_policy": alert_policy[:120],
            "reason": reason[:240],
            "status_code": status_code,
            "error": error,
            "fail_streak": max(0, fail_streak),
            "evidence": _domain_evidence(
                reason=reason,
                status_code=status_code,
                final_url=final_url,
                check_details=check_details,
            ),
        },
    )
    return details


def domain_recovered_details(
    *,
    domain: str,
    raw_entry: JsonObject | str,
    routes_telegram: bool,
    disabled: bool,
) -> JsonObject:
    """Build metadata that resolves the matching domain incident lane.

    Returns:
        A strict-JSON recovery details object with the same incident key.
    """
    inventory = _mapping(raw_entry)
    target_environment = _text(inventory.get("environment")) or "production"
    critical = bool(routes_telegram and target_environment == "production" and not disabled)
    details = _base_domain_details(
        domain=domain,
        inventory=inventory,
        critical=critical,
        target_environment=target_environment,
        fingerprint=_fingerprint({"domain": domain.lower(), "state": "recovered"}),
    )
    details.update(
        {
            "reason": "domain_recovered",
            "evidence": ["debounced domain health check recovered"],
        },
    )
    return details


def _base_domain_details(
    *,
    domain: str,
    inventory: JsonObject,
    critical: bool,
    target_environment: str,
    fingerprint: str,
) -> JsonObject:
    group = _text(inventory.get("group"))
    label = _text(inventory.get("label")) or domain
    details: JsonObject = {
        "domain": domain.lower(),
        "site": label,
        "service": "service-monitoring",
        "target_environment": target_environment,
        "incident_key": f"domain:{domain.lower()}",
        "incident_fingerprint": fingerprint,
        "severity": "critical" if critical else "warning",
        "alertable": critical,
        "critical": critical,
        "suppressed": not critical,
        "synthetic": False,
        "expected_behavior": _expected_behavior(domain=domain, inventory=inventory),
        "dashboard_url": _DASHBOARD_URL,
    }
    if group:
        details["project_group"] = group
        details["customer_group"] = group
    for field in ("project_id", "owner_project"):
        value = _text(inventory.get(field))
        if value:
            details[field] = value
    sources = _text_list(inventory.get("sources"))
    if sources:
        details["deployment_hint"] = f"inventory evidence: {', '.join(sources[:8])}"[:500]
    return details


def _expected_behavior(*, domain: str, inventory: JsonObject) -> str:
    check = _mapping(inventory.get("check"))
    allowed = _integer_list(check.get("allowed_status_codes")) or [200]
    url = _text(check.get("url")) or f"https://{domain}/"
    final_host = _text(check.get("expected_final_host_suffix"))
    behavior = f"{url} must satisfy HTTP {','.join(str(value) for value in allowed)}"
    if final_host:
        behavior += f" and finish on host suffix {final_host} after normal redirects"
    title = _text(check.get("expected_title_contains"))
    if title:
        behavior += f" with title containing {title!r}"
    return behavior[:500]


def _domain_evidence(
    *,
    reason: str,
    status_code: int | None,
    final_url: str | None,
    check_details: JsonObject,
) -> list[JsonValue]:
    evidence: list[JsonValue] = [f"reason={reason[:200]}"]
    if status_code is not None:
        evidence.append(f"status_code={status_code}")
    if final_url:
        evidence.append(f"final_url={final_url}")
    for field in (
        "final_host",
        "expected_final_host_suffix",
        "title",
        "missing_selectors_all",
        "missing_text",
        "forbidden_hits",
    ):
        value = check_details.get(field)
        if isinstance(value, (str, int, float, bool)):
            evidence.append(f"{field}={str(value)[:200]}")
        elif isinstance(value, list):
            visible_items = (str(item)[:80] for item in value[:5])
            joined = ", ".join(visible_items)
            if joined:
                evidence.append(f"{field}={joined}"[:240])
    return evidence[:_MAX_EVIDENCE_ITEMS]


def _fingerprint(material: JsonObject) -> str:
    encoded = json.dumps(material, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _mapping(value: JsonValue) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    return value


def _text(value: JsonValue) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:500]


def _bounded_text(value: JsonValue, *, limit: int) -> str | None:
    text = _text(value)
    return None if text is None else text[:limit]


def _integer(value: JsonValue) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _integer_list(value: JsonValue) -> list[int]:
    if not isinstance(value, list):
        return []
    integers: list[int] = []
    for item in value:
        integer = _integer(item)
        if integer is not None:
            integers.append(integer)
    return integers


def _text_list(value: JsonValue) -> list[str]:
    if not isinstance(value, list):
        return []
    texts: list[str] = []
    for item in value:
        text = _text(item)
        if text is not None:
            texts.append(text)
    return texts
