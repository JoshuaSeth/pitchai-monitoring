# Copyright (c) 2026 PitchAI. All rights reserved.
"""Resolve critical production-app signals to exact incident owner context."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .domain_event_models import ProductionIncidentRoute
from .json_types import bool_value, float_value, optional_object, text_value

if TYPE_CHECKING:
    from .domain_event_models import DomainIncidentPolicy
    from .json_types import JsonObject

_DOMAIN_SIGNAL_STATE_FIELDS = {
    "api_contract": "api_contract",
    "synthetic_transaction": "synthetic",
}


def current_production_routes(
    *,
    policies: dict[str, DomainIncidentPolicy],
    config: JsonObject,
    source_state: JsonObject,
) -> list[tuple[ProductionIncidentRoute, JsonObject]]:
    """Return all explicit critical app routes whose retained state is failing.

    Returns:
        Active route plus safe fallback evidence pairs.
    """
    routes: list[tuple[ProductionIncidentRoute, JsonObject]] = []
    for signal, state_field in _DOMAIN_SIGNAL_STATE_FIELDS.items():
        signal_state = optional_object(source_state.get(state_field))
        statuses = optional_object(signal_state.get("last_ok"))
        for domain, raw_status in statuses.items():
            if bool_value(raw_status) is not False:
                continue
            route = _domain_route(signal, domain=domain, policies=policies)
            if route is not None:
                routes.append((route, fallback_production_evidence(signal, domain=domain)))
    proxy_state = optional_object(source_state.get("proxy"))
    if bool_value(proxy_state.get("last_ok")) is False:
        proxy_route = _proxy_route(config)
        if proxy_route is not None:
            routes.append((proxy_route, fallback_production_evidence("reverse_proxy", domain=None)))
    return routes


def production_route_for_event(
    event: JsonObject,
    *,
    signal: str | None,
    policies: dict[str, DomainIncidentPolicy],
    config: JsonObject,
) -> ProductionIncidentRoute | None:
    """Resolve one retained transition only when policy makes it critical.

    Returns:
        Exact route for an alertable production surface, otherwise ``None``.
    """
    if signal == "reverse_proxy":
        return _proxy_route(config)
    if signal in _DOMAIN_SIGNAL_STATE_FIELDS:
        return _domain_route(signal, domain=text_value(event.get("domain")), policies=policies)
    return None


def fallback_production_evidence(signal: str, *, domain: str | None) -> JsonObject:
    """Return safe evidence when retained state outlives its opening event.

    Returns:
        Minimal current-state evidence for persistent-failure escalation.
    """
    open_kinds = {
        "api_contract": "api_contract_degraded",
        "synthetic_transaction": "synthetic_degraded",
        "reverse_proxy": "proxy_degraded",
    }
    evidence: JsonObject = {
        "kind": open_kinds.get(signal, "production_failure"),
        "reason": f"debounced {signal} production state is failing",
        "telegram_alert": True,
    }
    if domain:
        evidence["domain"] = domain
    return evidence


def _domain_route(
    signal: str,
    *,
    domain: str,
    policies: dict[str, DomainIncidentPolicy],
) -> ProductionIncidentRoute | None:
    policy = policies.get(domain)
    if policy is None or not policy.alertable:
        return None
    if signal == "api_contract":
        expected = f"All configured API contracts for {domain} must pass after production debouncing."
        fix_path = "Inspect the failing API route, application logs, runtime configuration, and most recent deploy."
    else:
        expected = f"All configured production synthetic transactions for {domain} must complete successfully."
        fix_path = "Inspect the failed transaction phase, app logs, runtime data path, and most recent deploy."
    return ProductionIncidentRoute(
        signal=signal,
        site=domain,
        domain=domain,
        owner_project=policy.owner_project,
        project_group=policy.group,
        group_label=policy.group_label,
        incident_key=f"production:{signal}:{domain}",
        expected_behavior=expected,
        source_hints=policy.sources,
        logs_hint=f"Inspect service-monitoring and {domain} application logs for the failed {signal} check.",
        likely_fix_path=fix_path,
    )


def _proxy_route(config: JsonObject) -> ProductionIncidentRoute | None:
    proxy = optional_object(config.get("proxy"))
    if bool_value(proxy.get("enabled")) is not True or bool_value(proxy.get("dispatch_on_degraded")) is not True:
        return None
    percent = float_value(proxy.get("max_502_504_percent"))
    upstream_max = float_value(proxy.get("max_upstream_errors_per_domain"))
    expected = (
        "PitchAI production reverse-proxy upstream checks must pass"
        f" with 502/504 rate at or below {percent}% and per-domain upstream errors below {upstream_max}."
    )
    return ProductionIncidentRoute(
        signal="reverse_proxy",
        site="PitchAI production reverse proxy",
        domain=None,
        owner_project="pitchai_infrastructure",
        project_group="infrastructure",
        group_label="Platform infrastructure",
        incident_key="production:reverse_proxy:global",
        expected_behavior=expected,
        source_hints=("/var/log/nginx/access.log", "/var/log/nginx/error.log", "domain_checks/config.yaml"),
        logs_hint="Inspect the bounded Nginx access/error windows and service-monitoring proxy signal evidence.",
        likely_fix_path=(
            "Repair the failing upstream, failover route, Nginx configuration, or deployed app behind the proxy."
        ),
    )
