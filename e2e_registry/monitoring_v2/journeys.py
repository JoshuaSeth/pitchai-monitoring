# Copyright (c) 2026 PitchAI. All rights reserved.
"""Aggregate retained E2E registry data into the monitoring Journeys tab."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from domain_checks.json_types import (
    bool_value,
    float_value,
    int_value,
    json_object,
    object_list,
    optional_object,
    text_value,
)
from domain_checks.safe_evidence import safe_public_url, safe_text_excerpt

if TYPE_CHECKING:
    from domain_checks.json_types import (
        JsonInput,
        JsonObject,
        JsonValue,
    )


def _binary_flag(value: JsonValue) -> bool | None:
    strict = bool_value(value)
    if strict is not None:
        return strict
    number = int_value(value)
    if number == 0:
        return False
    if number == 1:
        return True
    return None


def _journey_status(test: JsonObject, *, now_ts: float) -> tuple[str, float | None, float | None]:
    enabled = _binary_flag(test.get("enabled"))
    finished_at = float_value(test.get("last_finished_at_ts"))
    age_seconds = max(0.0, now_ts - finished_at) if finished_at is not None else None
    interval_seconds = int_value(test.get("interval_seconds"))
    stale_after = max(900, interval_seconds * 3) if interval_seconds and interval_seconds > 0 else None
    effective_ok = _binary_flag(test.get("effective_ok"))
    last_status = text_value(test.get("last_status"), default="unknown")
    status = "passing"
    if enabled is False:
        status = "disabled"
    elif enabled is None:
        status = "unknown"
    elif finished_at is None:
        status = "never_run"
    elif last_status == "infra_degraded":
        status = "infra_degraded"
    elif effective_ok is False:
        status = "failing"
    elif effective_ok is None or stale_after is None:
        status = "unknown"
    elif age_seconds is not None and age_seconds > stale_after:
        status = "stale"
    return status, age_seconds, stale_after


def _host(value: JsonValue) -> str:
    safe_url = safe_public_url(value)
    if not safe_url:
        return ""
    return (urlsplit(safe_url).hostname or "").lower()


def _dispatch_by_test(value: JsonInput) -> dict[str, JsonObject]:
    latest: dict[str, JsonObject] = {}
    for run in object_list(value):
        context = run.get("context")
        test_id = text_value(context.get("test_id")) if isinstance(context, dict) else ""
        if not test_id:
            continue
        current = latest.get(test_id)
        created = float_value(run.get("created_at_ts")) or 0.0
        current_created = float_value(current.get("created_at_ts")) if current else None
        if current is None or created >= (current_created or 0.0):
            latest[test_id] = run
    return latest


def _owners_by_domain(domains: list[JsonObject]) -> dict[str, str]:
    owners: dict[str, str] = {}
    for domain in domains:
        domain_name = text_value(domain.get("domain")).lower()
        if domain_name:
            owners[domain_name] = text_value(domain.get("group_label"), default="Unconfigured")
    return owners


def _journey_item(
    test: JsonObject,
    *,
    owners: dict[str, str],
    dispatch: dict[str, JsonObject],
    now_ts: float,
) -> tuple[JsonObject, float | None]:
    test_id = text_value(test.get("test_id"))
    status, age_seconds, stale_after = _journey_status(test, now_ts=now_ts)
    finished_at = float_value(test.get("last_finished_at_ts"))
    base_url = safe_public_url(test.get("base_url"))
    host = _host(base_url)
    latest_dispatch = dispatch.get(test_id, {})
    return (
        json_object({
            "test_id": test_id,
            "test_name": safe_text_excerpt(test.get("test_name"), max_chars=160) or "Unnamed journey",
            "test_kind": safe_text_excerpt(test.get("test_kind"), max_chars=80) or "journey",
            "base_url": base_url,
            "host": host or None,
            "owner_project": owners.get(host, "Unconfigured"),
            "status": status,
            "enabled": _binary_flag(test.get("enabled")),
            "effective_ok": _binary_flag(test.get("effective_ok")),
            "last_status": safe_text_excerpt(test.get("last_status"), max_chars=120),
            "last_finished_at_ts": finished_at,
            "last_ok_at_ts": float_value(test.get("last_ok_ts")),
            "last_fail_at_ts": float_value(test.get("last_fail_ts")),
            "age_seconds": age_seconds,
            "stale_after_seconds": stale_after,
            "interval_seconds": int_value(test.get("interval_seconds")),
            "elapsed_ms": float_value(test.get("last_elapsed_ms")),
            "fail_streak": int_value(test.get("fail_streak")) or 0,
            "success_streak": int_value(test.get("success_streak")) or 0,
            "next_due_at_ts": float_value(test.get("next_due_ts")),
            "dispatch": {
                "state": safe_text_excerpt(latest_dispatch.get("queue_state"), max_chars=80),
                "created_at_ts": float_value(latest_dispatch.get("created_at_ts")),
                "ui_url": safe_public_url(latest_dispatch.get("ui_url")),
            },
        }),
        finished_at,
    )


def _journey_items(
    tests: list[JsonObject],
    *,
    owners: dict[str, str],
    dispatch: dict[str, JsonObject],
    now_ts: float,
) -> tuple[list[JsonObject], float | None]:
    items: list[JsonObject] = []
    latest_run: float | None = None
    for test in tests:
        item, finished_at = _journey_item(test, owners=owners, dispatch=dispatch, now_ts=now_ts)
        items.append(item)
        if finished_at is not None:
            latest_run = finished_at if latest_run is None else max(latest_run, finished_at)
    return items, latest_run


def _status_counts(items: list[JsonObject]) -> dict[str, int]:
    statuses = (
        "passing",
        "failing",
        "stale",
        "infra_degraded",
        "never_run",
        "unknown",
        "disabled",
    )
    counts: dict[str, int] = dict.fromkeys(statuses, 0)
    for item in items:
        status = text_value(item.get("status"))
        if status in counts:
            counts[status] += 1
    return counts


def _overall_status(counts: dict[str, int]) -> str:
    if counts["failing"]:
        return "attention"
    if counts["stale"] or counts["infra_degraded"] or counts["never_run"] or counts["unknown"]:
        return "incomplete"
    return "healthy"


def build_journeys(
    *,
    e2e_status: JsonInput,
    dispatch_runs: JsonInput,
    domains: list[JsonObject],
    now_ts: float,
) -> JsonObject:
    """Build real journey state and explicit missing/stale classifications.

    Returns:
        Sanitized journey rows, counts, freshness, and dispatch links.
    """
    status_object = optional_object(e2e_status)
    raw_status = status_object.get("ok")
    if _binary_flag(raw_status) is not True:
        return json_object({
            "status": "unavailable",
            "data_state": "unavailable",
            "total": None,
            "passing": None,
            "failing": None,
            "stale": None,
            "infra_degraded": None,
            "never_run": None,
            "unknown": None,
            "disabled": None,
            "latest_run_at_ts": None,
            "latest_run_age_seconds": None,
            "items": [],
        })
    tests = object_list(status_object.get("tests"))
    owners = _owners_by_domain(domains)
    dispatch = _dispatch_by_test(dispatch_runs)
    items, latest_run = _journey_items(tests, owners=owners, dispatch=dispatch, now_ts=now_ts)
    counts = _status_counts(items)
    enabled_total = len(items) - counts["disabled"]
    return json_object({
        "status": _overall_status(counts),
        "data_state": "available" if items else "missing",
        "total": enabled_total,
        "passing": counts["passing"],
        "failing": counts["failing"],
        "stale": counts["stale"],
        "infra_degraded": counts["infra_degraded"],
        "never_run": counts["never_run"],
        "unknown": counts["unknown"],
        "disabled": counts["disabled"],
        "latest_run_at_ts": latest_run,
        "latest_run_age_seconds": max(0.0, now_ts - latest_run) if latest_run is not None else None,
        "items": items,
    })
