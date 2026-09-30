# Copyright (c) 2026 PitchAI. All rights reserved.
"""Role-specific progress extraction for the monitoring service health contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from .json_types import optional_object, text_value
from .service_health_evidence import (
    age_seconds,
    error_token,
    parse_iso_epoch_seconds,
    parse_json_number,
    sanitize_fragment,
)
from .service_health_state import ProgressEvidence

if TYPE_CHECKING:
    from .json_types import JsonObject, JsonValue
    from .service_health_state import ProgressContext

_DEPENDENCY_STATE_VERSION: Final = 2
_RUNNING_PHASE: Final = "running"
_CLAIM_FAILURE_LIMIT: Final = 3.0
_SUPPORTED_DEPENDENCY_STATES: Final = frozenset({"ok", "healthy"})


def monitor_progress(payload: JsonObject, _context: ProgressContext) -> ProgressEvidence:
    """Return the monitor cycle progress recorded in the retained domain state.

    Args:
        payload: Retained ``state.json`` document written once per cycle.
        _context: Unused; the shared decision table owns threshold evaluation.

    Returns:
        Progress evidence keyed off the cycle stamp, degraded when the monitor
        itself cannot run browser probes or write its own state document.
    """
    write_fail_streak = parse_json_number(optional_object(payload.get("meta")).get("state_write_fail_streak"))
    degraded_reason: str | None = None
    if write_fail_streak is not None and write_fail_streak > 0:
        degraded_reason = "state_write_failing"
    elif payload.get("browser_degraded_active") is True:
        degraded_reason = "browser_probe_degraded"
    return ProgressEvidence(
        timestamp=parse_iso_epoch_seconds(payload.get("updated_at")),
        degraded_reason=degraded_reason,
        stale_reason="monitor_progress_stale",
        detail=(_count_detail("state_write_fail_streak", write_fail_streak),),
    )


def runner_heartbeat_progress(payload: JsonObject, context: ProgressContext) -> ProgressEvidence:
    """Return runner loop progress without depending on completed runs.

    Args:
        payload: Retained runner heartbeat document.
        context: Times and thresholds for this evaluation.

    Returns:
        Progress evidence keyed off the loop heartbeat, or off the in-flight
        job start while a legitimate long test is still holding the loop.
    """
    phase = text_value(payload.get("phase"), default="unknown")
    claim_failures = parse_json_number(payload.get("consecutive_claim_failures"))
    detail = (
        f"phase={sanitize_fragment(phase)}",
        _count_detail("completed_jobs", parse_json_number(payload.get("completed_jobs"))),
        _count_detail("claim_failure_streak", claim_failures),
    )
    if phase == _RUNNING_PHASE:
        return ProgressEvidence(
            timestamp=parse_json_number(payload.get("active_job_started_ts")),
            stale_reason="runner_job_overrun",
            stale_seconds=context.extended_seconds,
            detail=detail,
        )
    degraded_reason: str | None = None
    if claim_failures is not None and claim_failures >= _CLAIM_FAILURE_LIMIT:
        degraded_reason = f"registry_claim_failing:{_classifier_token(payload.get('last_claim_error'))}"
    return ProgressEvidence(
        timestamp=parse_json_number(payload.get("updated_at_ts")),
        degraded_reason=degraded_reason,
        stale_reason="runner_poll_stale",
        detail=detail,
    )


def database_dependency_progress(payload: JsonObject, _context: ProgressContext) -> ProgressEvidence:
    """Return collector progress that stays independent of dependency health.

    Args:
        payload: Retained database dependency snapshot.
        _context: Unused; the shared decision table owns threshold evaluation.

    Returns:
        Progress evidence keyed off the newest collector or generated stamp, so
        a failing monitored database never restarts the collector itself.

    Raises:
        ValueError: If the snapshot is not the supported state version.
    """
    version = payload.get("version")
    if version != _DEPENDENCY_STATE_VERSION:
        message = f"unsupported database dependency state version {sanitize_fragment(version)}"
        raise ValueError(message)
    collector = optional_object(payload.get("collector"))
    dependencies = payload.get("dependencies")
    return ProgressEvidence(
        timestamp=_latest_stamp(
            parse_json_number(collector.get("last_successful_cycle_at_ts")),
            parse_json_number(collector.get("observed_at_ts")),
            parse_json_number(payload.get("generated_at_ts")),
        ),
        degraded_reason=_collector_reason(collector=collector, payload=payload),
        stale_reason="collector_progress_stale",
        detail=(
            f"collector_status={sanitize_fragment(collector.get('status'))}",
            f"dependencies={_list_size(dependencies)}",
            f"dependencies_down={_down_count(dependencies)}",
            f"dependency_status={sanitize_fragment(payload.get('status'))}",
        ),
    )


def scheduler_observer_progress(payload: JsonObject, context: ProgressContext) -> ProgressEvidence:
    """Return observer loop progress, keeping central-feed failures degraded.

    Args:
        payload: Retained scheduler placement observer snapshot.
        context: Times and thresholds for this evaluation.

    Returns:
        Progress evidence keyed off the poll stamp, degraded while the observer
        records a poll failure or has not reached central successfully for the
        role's extended window.
    """
    successful_poll = parse_json_number(payload.get("last_successful_poll_at_ts"))
    central_poll_stale = (
        successful_poll is not None
        and age_seconds(context.now, successful_poll) > float(context.extended_seconds)
    )
    degraded_reason = _cycle_error_reason(payload.get("last_error"))
    if degraded_reason is None and central_poll_stale:
        degraded_reason = "central_poll_stale"
    return ProgressEvidence(
        timestamp=parse_json_number(payload.get("updated_at_ts")),
        degraded_reason=degraded_reason,
        stale_reason="observer_progress_stale",
        detail=(_age_detail("central_poll_age_seconds", context.now, successful_poll),),
    )


def domain_incident_progress(payload: JsonObject, _context: ProgressContext) -> ProgressEvidence:
    """Return domain incident producer progress and Events Bus outbox backlog.

    Args:
        payload: Retained domain incident events producer snapshot.
        _context: Unused; the shared decision table owns threshold evaluation.

    Returns:
        Progress evidence keyed off the producer stamp, degraded while the
        producer records a delivery failure.
    """
    producer = optional_object(payload.get("producer"))
    detail = [f"producer_status={sanitize_fragment(producer.get('status'))}"]
    for name, raw_count in (
        ("pending_outbox", producer.get("pending_count")),
        ("open_incidents", producer.get("open_incident_count")),
    ):
        count = parse_json_number(raw_count)
        if count is not None:
            detail.append(f"{name}={round(count)}")
    return ProgressEvidence(
        timestamp=parse_json_number(producer.get("updated_at_ts")),
        degraded_reason=_cycle_error_reason(producer.get("last_error")),
        stale_reason="producer_progress_stale",
        detail=tuple(detail),
    )


def _cycle_error_reason(value: JsonValue) -> str | None:
    """Return a narrow cycle-failure reason, ``None`` when none is recorded."""
    recorded = text_value(value)
    if not recorded:
        return None
    return f"cycle_error:{_classifier_token(recorded)}"


def _classifier_token(value: JsonValue) -> str:
    """Return the trailing lower-case classifier of retained error text.

    Retained failures are written as ``phase:Classifier`` and free-form text
    stays hidden behind the narrow token rule, so nothing secret is published.
    """
    return error_token(text_value(value).rpartition(":")[2].lower())


def _collector_reason(*, collector: JsonObject, payload: JsonObject) -> str | None:
    """Return the collector-side failure reason, ``None`` while it is healthy."""
    collector_status = text_value(collector.get("status"))
    if collector_status and collector_status != "healthy":
        return f"collector_cycle_failed:{_classifier_token(collector.get('error_class'))}"
    dependency_status = text_value(payload.get("status"))
    if dependency_status and dependency_status not in _SUPPORTED_DEPENDENCY_STATES:
        return f"dependency_unhealthy:{error_token(dependency_status)}"
    return None


def _list_size(value: JsonValue) -> int:
    """Return the number of retained entries in one optional list."""
    if isinstance(value, list):
        return len(value)
    return 0


def _down_count(dependencies: JsonValue) -> int:
    """Return how many retained dependencies currently report ``down``."""
    if not isinstance(dependencies, list):
        return 0
    failing = 0
    for entry in dependencies:
        if text_value(optional_object(entry).get("status")) == "down":
            failing += 1
    return failing


def _latest_stamp(*candidates: float | None) -> float | None:
    observed = [candidate for candidate in candidates if candidate is not None]
    return max(observed) if observed else None


def _age_detail(name: str, now: float, timestamp: float | None) -> str:
    if timestamp is None:
        return f"{name}=none"
    return f"{name}={round(age_seconds(now, timestamp))}"


def _count_detail(name: str, value: float | None) -> str:
    rendered = "none" if value is None else str(round(value))
    return f"{name}={rendered}"
