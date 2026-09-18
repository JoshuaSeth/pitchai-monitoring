# Copyright (c) 2026 PitchAI. All rights reserved.
"""Aggregate retained availability, SLO and event history for Reliability."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from .json_types import (
    bool_value,
    float_value,
    json_object,
    object_list,
    optional_object,
    text_value,
)
from .reliability_events import build_event_history
from .reliability_metrics import (
    PERCENT,
    WINDOW_SECONDS,
    availability,
    percentile,
    samples_for_group,
    trend,
)

if TYPE_CHECKING:
    from .json_types import (
        JsonObject,
        JsonValue,
    )


class _BudgetMetrics(NamedTuple):
    """Availability and error-budget values for one domain group."""

    total: int
    successful: int
    availability: float | None
    consumed: float | None
    remaining: float | None


class _MemberCounts(NamedTuple):
    """Current service health counts for one domain group."""

    healthy: int
    alertable_down: int
    expected_down: int


def _group_definitions(
    summary: JsonObject,
    domains: list[JsonObject],
) -> list[JsonObject]:
    configured = object_list(summary.get("domain_groups"))
    if configured:
        return configured
    definitions: dict[str, JsonObject] = {}
    for domain in domains:
        group_id = text_value(domain.get("group"), default="unconfigured")
        definitions[group_id] = {
            "id": group_id,
            "label": text_value(
                domain.get("group_label"),
                default=group_id.replace("-", " ").title(),
            ),
            "description": domain.get("group_description"),
        }
    return list(definitions.values())


def _budget_metrics(
    samples: list[list[JsonValue]],
    *,
    target: float | None,
) -> _BudgetMetrics:
    total, successful, availability_value = availability(samples)
    allowed_error = PERCENT - target if target is not None else None
    observed_error = PERCENT - availability_value if availability_value is not None else None
    consumed = observed_error / allowed_error * PERCENT if observed_error is not None and allowed_error else None
    remaining = max(0.0, PERCENT - consumed) if consumed is not None else None
    return _BudgetMetrics(total, successful, availability_value, consumed, remaining)


def _member_counts(members: list[JsonObject]) -> _MemberCounts:
    healthy = 0
    alertable_down = 0
    expected_down = 0
    for domain in members:
        domain_ok = bool_value(optional_object(domain.get("last")).get("ok"))
        telegram_enabled = bool_value(
            optional_object(domain.get("alert_policy")).get("telegram_enabled"),
        )
        if domain_ok is True:
            healthy += 1
        elif domain_ok is False and telegram_enabled is False:
            expected_down += 1
        elif domain_ok is False:
            alertable_down += 1
    return _MemberCounts(healthy, alertable_down, expected_down)


def _group_status(budget: _BudgetMetrics, counts: _MemberCounts) -> str:
    if not budget.total:
        return "insufficient_data"
    if counts.alertable_down or (budget.consumed is not None and budget.consumed >= PERCENT):
        return "attention"
    if counts.expected_down:
        return "expected"
    return "healthy"


def _group_row(
    definition: JsonObject,
    *,
    domains: list[JsonObject],
    state: JsonObject,
    target: float | None,
    now_ts: float,
) -> JsonObject:
    group_id = text_value(definition.get("id"))
    group_members = [domain for domain in domains if text_value(domain.get("group")) == group_id]
    members = [domain for domain in group_members if bool_value(domain.get("disabled")) is not True]
    samples = samples_for_group(domains, group_id=group_id, state=state, now_ts=now_ts)
    budget = _budget_metrics(samples, target=target)
    counts = _member_counts(members)
    return json_object(
        {
            "id": group_id,
            "label": definition.get("label"),
            "description": definition.get("description"),
            "status": _group_status(budget, counts),
            "services": len(members),
            "healthy": counts.healthy,
            "alertable_down": counts.alertable_down,
            "expected_down": counts.expected_down,
            "observations_24h": budget.total,
            "successful_observations_24h": budget.successful,
            "availability_24h_pct": budget.availability,
            "slo_target_pct": target,
            "error_budget_consumed_pct": budget.consumed,
            "error_budget_remaining_pct": budget.remaining,
            "http_p95_ms": percentile(samples, index=2),
            "browser_p95_ms": percentile(samples, index=3),
            "trend_24h": trend(samples, now_ts=now_ts),
        },
    )


def _routing(domains: list[JsonObject]) -> JsonObject:
    enabled = [domain for domain in domains if bool_value(domain.get("disabled")) is not True]
    routed = sum(
        bool_value(optional_object(domain.get("alert_policy")).get("telegram_enabled")) is not False
        for domain in enabled
    )
    return {
        "enabled_services": len(enabled),
        "telegram_alertable": routed,
        "dashboard_only": len(enabled) - routed,
        "channel": "Telegram",
    }


def _reliability_status(groups: list[JsonObject], *, target: float | None) -> str:
    statuses = {text_value(group.get("status")) for group in groups}
    if "attention" in statuses:
        return "attention"
    if "expected" in statuses:
        return "expected"
    if not groups:
        return "unavailable"
    if target is None:
        return "incomplete"
    return "healthy"


def build_reliability(
    *,
    summary: JsonObject,
    state: JsonObject,
    config: JsonObject,
    events: list[JsonObject],
    now_ts: float,
) -> JsonObject:
    """Build grouped SLO posture, routing policy and retained incident history.

    Returns:
        Current per-group SLO rows, alert routing, and event history.
    """
    domains = object_list(summary.get("domains"))
    target = float_value(optional_object(config.get("slo")).get("target_percent"))
    if target is not None and not 0.0 < target < PERCENT:
        target = None
    definitions = _group_definitions(summary, domains)
    groups = [
        _group_row(
            definition,
            domains=domains,
            state=state,
            target=target,
            now_ts=now_ts,
        )
        for definition in definitions
    ]
    return json_object(
        {
            "status": _reliability_status(groups, target=target),
            "window_seconds": int(WINDOW_SECONDS),
            "slo_target_pct": target,
            "groups": groups,
            "routing": _routing(domains),
            "event_history": build_event_history(events, domains, now_ts=now_ts),
            "data_state": "unavailable" if not groups else "available" if target is not None else "missing_config",
        },
    )
