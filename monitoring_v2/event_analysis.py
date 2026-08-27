# Copyright (c) 2026 PitchAI. All rights reserved.
"""Retained-event and sample analysis for actionable monitoring incidents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .json_types import (
    bool_value,
    float_value,
    int_value,
    object_list,
    text_value,
    value_list,
)
from .safe_evidence import safe_public_url, safe_text_excerpt

if TYPE_CHECKING:
    from .json_types import (
        JsonObject,
        JsonValue,
    )

_TRANSITIONS = {
    "primary": ("domain_down", "domain_up"),
    "api_contract": ("api_contract_degraded", "api_contract_recovered"),
    "synthetic": ("synthetic_degraded", "synthetic_recovered"),
}
_MIN_OBSERVATION_FIELDS = 2
_STATUS_CODE_FIELDS = 5


def event_is_problem(kind: str) -> bool:
    """Return whether a retained event kind represents degradation."""
    normalized = kind.strip().lower()
    return normalized.endswith(("_down", "_degraded", "_failed", "_failure", "_error", "_unhealthy"))


def event_is_recovery(kind: str) -> bool:
    """Return whether a retained event kind represents recovery."""
    normalized = kind.strip().lower()
    return normalized.endswith(("_up", "_recovered", "_healthy"))


def safe_events(value: JsonValue | object) -> list[JsonObject]:
    """Return a bounded, dashboard-safe copy of retained monitor events."""
    events: list[JsonObject] = []
    for raw in object_list(value)[-2_000:]:
        timestamp = float_value(raw.get("ts"))
        kind = safe_text_excerpt(raw.get("kind"), max_chars=120)
        if timestamp is None or not kind:
            continue
        event: JsonObject = {"ts": timestamp, "kind": kind}
        domain = safe_text_excerpt(raw.get("domain"), max_chars=253)
        if domain:
            event["domain"] = domain
        for key in ("reason", "error", "violations", "check_name", "content_type"):
            cleaned = safe_text_excerpt(raw.get(key), max_chars=240)
            if cleaned:
                event[key] = cleaned
        excerpt = safe_text_excerpt(raw.get("response_excerpt"), max_chars=360)
        if excerpt:
            event["response_excerpt"] = excerpt
        final_url = safe_public_url(raw.get("final_url"))
        if final_url:
            event["final_url"] = final_url
        for key in ("status_code", "failures", "fail_streak"):
            number = int_value(raw.get(key))
            if number is not None:
                event[key] = number
        telegram_alert = bool_value(raw.get("telegram_alert"))
        if telegram_alert is not None:
            event["telegram_alert"] = telegram_alert
        events.append(event)
    return events


def active_transition_start(
    events: list[JsonObject],
    *,
    problem_kind: str,
    recovery_kind: str,
    domain: str,
) -> float | None:
    """Return the start of a retained problem interval that has no later recovery."""
    latest_problem: float | None = None
    latest_recovery: float | None = None
    for event in events:
        if text_value(event.get("domain")) != domain:
            continue
        timestamp = float_value(event.get("ts"))
        if timestamp is None:
            continue
        kind = text_value(event.get("kind")).lower()
        if kind == problem_kind:
            latest_problem = timestamp if latest_problem is None else max(latest_problem, timestamp)
        elif kind == recovery_kind:
            latest_recovery = timestamp if latest_recovery is None else max(latest_recovery, timestamp)
    if latest_problem is None or (latest_recovery is not None and latest_recovery > latest_problem):
        return None
    return latest_problem


def domain_first_seen(
    *,
    domain: str,
    failure_sources: list[str],
    events: list[JsonObject],
    history: list[JsonValue],
) -> float | None:
    """Find the earliest supported start for the current effective domain failure.

    Returns:
        Earliest retained active-failure timestamp, when available.
    """
    starts: list[float] = []
    for source in failure_sources:
        transition = _TRANSITIONS.get(source)
        if transition is None:
            continue
        started = active_transition_start(
            events,
            problem_kind=transition[0],
            recovery_kind=transition[1],
            domain=domain,
        )
        if started is not None:
            starts.append(started)
    if "primary" in failure_sources:
        primary_start = current_failed_run_start(history)
        if primary_start is not None:
            starts.append(primary_start)
    return min(starts) if starts else None


def current_failed_run_start(history: list[JsonValue]) -> float | None:
    """Return the first timestamp in the trailing run of failed samples."""
    list_samples = (item for item in history if isinstance(item, list))
    samples = [value_list(item) for item in list_samples]
    if not samples or len(samples[-1]) < _MIN_OBSERVATION_FIELDS or bool_value(samples[-1][1]) is not False:
        return None
    started: float | None = None
    for sample in reversed(samples):
        if len(sample) < _MIN_OBSERVATION_FIELDS or bool_value(sample[1]) is not False:
            break
        timestamp = float_value(sample[0])
        if timestamp is not None:
            started = timestamp
    return started


def latest_problem_event(
    *,
    domain: str,
    failure_sources: list[str],
    events: list[JsonObject],
) -> JsonObject:
    """Return the newest retained transition event for the active failure sources."""
    kinds: set[str] = set()
    for source in failure_sources:
        if source in _TRANSITIONS:
            kinds.add(_TRANSITIONS[source][0])
    candidates: list[JsonObject] = []
    for event in events:
        same_domain = text_value(event.get("domain")) == domain
        matching_kind = text_value(event.get("kind")).lower() in kinds
        if same_domain and matching_kind:
            candidates.append(event)
    return max(candidates, key=lambda event: float_value(event.get("ts")) or 0.0) if candidates else {}


def last_successful_sample(history: list[JsonValue]) -> JsonObject | None:
    """Return the newest retained successful domain observation."""
    for raw in reversed(history):
        sample = value_list(raw)
        if len(sample) >= _MIN_OBSERVATION_FIELDS and bool_value(sample[1]) is True:
            result: JsonObject = {
                "observed_at_ts": float_value(sample[0]),
                "source": "retained history",
            }
            if len(sample) >= _STATUS_CODE_FIELDS:
                result["status_code"] = int_value(sample[4])
            return result
    return None
