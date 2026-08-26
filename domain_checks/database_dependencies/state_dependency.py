# Copyright (c) 2026 PitchAI. All rights reserved.
"""Reduce one database probe observation into retained dashboard state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

from domain_checks.database_dependencies.models import definition_contract
from domain_checks.json_types import bool_value, float_value, int_value, text_value

if TYPE_CHECKING:
    from domain_checks.database_dependencies.models import (
        DatabaseDependencySettings,
        ProbeDefinition,
        ProbeObservation,
    )
    from domain_checks.json_types import JsonObject

_AUTH_FAILURES = {
    "credential_missing",
    "credential_unreadable",
    "invalid_or_revoked_password",
    "login_or_authentication_failure",
}
_ALERTABLE_DATABASE_FAILURES = _AUTH_FAILURES | {
    "database_connection_failure",
    "database_file_unreachable",
    "database_or_pgbouncer_unreachable",
    "missing_relation_grant",
    "missing_schema_grant",
    "missing_table_or_materialized_view",
    "query_permission_failure",
    "timeout",
}


@dataclass(frozen=True)
class _ProbeStreaks:
    """Consecutive outcome counts for one dependency."""

    failure: int
    success: int


class _RetainedTimeline(NamedTuple):
    """Current and historical timestamps retained for one dependency."""

    last_success_at_ts: float | None
    last_failure_at_ts: float | None
    last_success_latency_ms: float | None
    last_failure_latency_ms: float | None
    failure_started_at_ts: float | None
    last_failure_started_at_ts: float | None
    last_failure_class: str | None
    last_failure_excerpt: str | None


def _streak(previous: JsonObject, observation: ProbeObservation) -> _ProbeStreaks:
    previous_ok = bool_value(previous.get("observed_ok"))
    if observation.ok:
        prior = int_value(previous.get("success_streak")) or 0
        return _ProbeStreaks(failure=0, success=prior + 1 if previous_ok is True else 1)
    prior = int_value(previous.get("failure_streak")) or 0
    return _ProbeStreaks(failure=prior + 1 if previous_ok is False else 1, success=0)


def _static_alert_enabled(definition: ProbeDefinition) -> bool:
    return bool(
        definition.dependency_kind == "database"
        and definition.environment == "production"
        and definition.critical
        and definition.telegram_policy_enabled
        and definition.telegram_route_eligible,
    )


def _status(
    previous: JsonObject,
    observation: ProbeObservation,
    settings: DatabaseDependencySettings,
    *,
    definition: ProbeDefinition,
    streaks: _ProbeStreaks,
) -> str:
    if not observation.ok:
        alertable_failure = bool(
            _static_alert_enabled(definition) and observation.failure_class in _ALERTABLE_DATABASE_FAILURES,
        )
        if alertable_failure and streaks.failure >= settings.down_after_failures:
            return "down"
        return "degraded"
    prior_status = text_value(previous.get("status"))
    if prior_status == "down" and streaks.success < settings.up_after_successes:
        return "degraded"
    return "healthy"


def _failure_started(previous: JsonObject, observation: ProbeObservation) -> float | None:
    if observation.ok:
        return None
    if bool_value(previous.get("observed_ok")) is False:
        retained = float_value(previous.get("failure_started_at_ts"))
        if retained is not None:
            return retained
    return observation.observed_at_ts


def _credential_state(
    observation: ProbeObservation,
    *,
    last_success_at_ts: float | None,
) -> str:
    if observation.ok:
        return "current"
    if observation.failure_class not in _AUTH_FAILURES:
        return "current_or_unproven"
    if last_success_at_ts is not None:
        return "stale_or_revoked_after_last_success"
    return "missing_invalid_or_unproven"


def _suppression_reason(
    definition: ProbeDefinition,
    observation: ProbeObservation,
    *,
    status: str,
) -> str | None:
    static_reason = _static_suppression_reason(definition)
    if static_reason is not None:
        return static_reason
    if not observation.ok and observation.failure_class not in _ALERTABLE_DATABASE_FAILURES:
        return "monitoring_boundary_failure"
    if not observation.ok and status != "down":
        return "failure_debounce"
    return None


def _static_suppression_reason(definition: ProbeDefinition) -> str | None:
    if definition.telegram_suppression_reason is not None:
        return definition.telegram_suppression_reason
    if definition.dependency_kind != "database":
        return "coverage_gap_dashboard_only"
    if not definition.telegram_policy_enabled:
        return "dashboard_only_policy"
    if not definition.critical or definition.environment != "production":
        return "noncritical_or_nonproduction"
    return None


def _retained_timeline(previous: JsonObject, observation: ProbeObservation) -> _RetainedTimeline:
    failure_started_at_ts = _failure_started(previous, observation)
    return _RetainedTimeline(
        last_success_at_ts=(
            observation.observed_at_ts if observation.ok else float_value(previous.get("last_success_at_ts"))
        ),
        last_failure_at_ts=(
            observation.observed_at_ts if not observation.ok else float_value(previous.get("last_failure_at_ts"))
        ),
        last_success_latency_ms=(
            observation.latency_ms if observation.ok else float_value(previous.get("last_success_latency_ms"))
        ),
        last_failure_latency_ms=(
            observation.latency_ms if not observation.ok else float_value(previous.get("last_failure_latency_ms"))
        ),
        failure_started_at_ts=failure_started_at_ts,
        last_failure_started_at_ts=(
            failure_started_at_ts
            if failure_started_at_ts is not None
            else float_value(previous.get("last_failure_started_at_ts"))
        ),
        last_failure_class=(
            observation.failure_class if not observation.ok else text_value(previous.get("last_failure_class")) or None
        ),
        last_failure_excerpt=(
            observation.sanitized_error_excerpt
            if not observation.ok
            else text_value(previous.get("last_failure_excerpt")) or None
        ),
    )


def build_dependency_state(
    definition: ProbeDefinition,
    observation: ProbeObservation,
    previous: JsonObject,
    settings: DatabaseDependencySettings,
) -> JsonObject:
    """Reduce a single sanitized observation with debounce and stale-credential state.

    Returns:
        One complete secret-free database dependency dashboard row.
    """
    streaks = _streak(previous, observation)
    status = _status(
        previous,
        observation,
        settings,
        definition=definition,
        streaks=streaks,
    )
    timeline = _retained_timeline(previous, observation)
    telegram_alert_enabled = _static_alert_enabled(definition)
    telegram_alert_eligible = bool(
        telegram_alert_enabled and status == "down" and observation.failure_class in _ALERTABLE_DATABASE_FAILURES,
    )
    contract = definition_contract(definition)
    contract.update(
        {
            "status": status,
            "observed_at_ts": observation.observed_at_ts,
            "observed_ok": observation.ok,
            "latency_ms": observation.latency_ms,
            "last_success_at_ts": timeline.last_success_at_ts,
            "last_success_latency_ms": timeline.last_success_latency_ms,
            "last_failure_at_ts": timeline.last_failure_at_ts,
            "last_failure_latency_ms": timeline.last_failure_latency_ms,
            "failure_started_at_ts": timeline.failure_started_at_ts,
            "last_failure_started_at_ts": timeline.last_failure_started_at_ts,
            "failure_streak": streaks.failure,
            "success_streak": streaks.success,
            "failure_class": observation.failure_class,
            "failure_phase": observation.failure_phase,
            "sqlstate": observation.sqlstate,
            "sanitized_error_excerpt": observation.sanitized_error_excerpt,
            "last_failure_class": timeline.last_failure_class,
            "last_failure_excerpt": timeline.last_failure_excerpt,
            "credential_state": _credential_state(observation, last_success_at_ts=timeline.last_success_at_ts),
            "telegram_alert_enabled": telegram_alert_enabled,
            "telegram_alert_eligible": telegram_alert_eligible,
            "telegram_suppression_reason": _suppression_reason(
                definition,
                observation,
                status=status,
            ),
        },
    )
    return contract
