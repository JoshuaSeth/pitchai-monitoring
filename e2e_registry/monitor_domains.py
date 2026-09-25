# Copyright (c) 2026 PitchAI. All rights reserved.
"""Per-domain health aggregation for the monitoring dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from domain_checks.history import compute_availability, latency_percentile_ms, window_samples
from e2e_registry.monitor_inventory import normalize_domain_entries, normalize_domain_groups
from e2e_registry.monitor_values import monitor_mapping, safe_float, safe_int, safe_timestamp

if TYPE_CHECKING:
    from domain_checks.history import Sample
    from e2e_registry.monitor_types import MonitorData, MonitorRecord, MonitorRecords, MonitorValue

_DAY_SECONDS = 86_400.0
_TS_INDEX = 0
_OK_INDEX = 1
_HTTP_INDEX = 2
_BROWSER_INDEX = 3
_STATUS_INDEX = 4


@dataclass(frozen=True)
class _DomainContext:
    state: MonitorRecord
    config_by_domain: dict[str, MonitorRecord]
    groups_by_id: dict[str, MonitorRecord]
    now_ts: float
    http_slow_max: float | None
    browser_slow_max: float | None


def _sample_value(sample: MonitorValue, index: int) -> MonitorValue:
    if not isinstance(sample, list | tuple) or len(sample) <= index:
        return None
    return sample[index]


def _subcheck(state: MonitorRecord, key: str, domain: str) -> MonitorRecord:
    check = monitor_mapping(state.get(key))
    return {
        "last_ok": monitor_mapping(check.get("last_ok")).get(domain),
        "fail_streak": monitor_mapping(check.get("fail_streak")).get(domain),
        "success_streak": monitor_mapping(check.get("success_streak")).get(domain),
        "last_run_ts": safe_timestamp(monitor_mapping(check.get("last_run_ts")).get(domain)),
    }


def _last_primary_state(
    *,
    domain: str,
    last_sample: Sample | None,
    state: MonitorRecord,
) -> tuple[float | None, bool | None]:
    last_timestamp = safe_float(_sample_value(last_sample, _TS_INDEX))
    sample_ok = _sample_value(last_sample, _OK_INDEX)
    persisted_ok = monitor_mapping(state.get("last_ok")).get(domain)
    if sample_ok is not None:
        return last_timestamp, bool(sample_ok)
    if persisted_ok is not None:
        return last_timestamp, bool(persisted_ok)
    return last_timestamp, None


def _failure_sources(
    *,
    primary_ok: bool | None,
    api_contract: MonitorRecord,
    synthetic: MonitorRecord,
) -> list[str]:
    sources: list[str] = []
    if primary_ok is False:
        sources.append("primary")
    if api_contract.get("last_ok") is False:
        sources.append("api_contract")
    if synthetic.get("last_ok") is False:
        sources.append("synthetic")
    return sources


def _latest_summary(
    domain: str,
    items: list[Sample],
    state: MonitorRecord,
) -> tuple[MonitorRecord, MonitorRecord, MonitorRecord]:
    last_sample = items[-1] if items else None
    last_ts, last_ok = _last_primary_state(domain=domain, last_sample=last_sample, state=state)
    synthetic = _subcheck(state, "synthetic", domain)
    api_contract = _subcheck(state, "api_contract", domain)
    failure_sources = _failure_sources(
        primary_ok=last_ok,
        api_contract=api_contract,
        synthetic=synthetic,
    )
    candidate_timestamps = (last_ts, api_contract.get("last_run_ts"), synthetic.get("last_run_ts"))
    numeric_timestamps = (value for value in candidate_timestamps if isinstance(value, int | float))
    effective_timestamps = list(numeric_timestamps)
    last_status_code = safe_int(_sample_value(last_sample, _STATUS_INDEX))
    latest = cast(
        "MonitorRecord",
        {
            "ts": max(effective_timestamps) if effective_timestamps else None,
            "primary_ts": last_ts,
            "ok": False if failure_sources else last_ok,
            "primary_ok": last_ok,
            "failure_sources": failure_sources,
            "http_ms": safe_float(_sample_value(last_sample, _HTTP_INDEX)),
            "browser_ms": safe_float(_sample_value(last_sample, _BROWSER_INDEX)),
            "status_code": last_status_code if last_ok is False or not failure_sources else None,
            "primary_status_code": last_status_code,
        },
    )
    return latest, synthetic, api_contract


def _window_summary(items: list[Sample], context: _DomainContext) -> MonitorRecord:
    recent = window_samples(items, since_ts=context.now_ts - _DAY_SECONDS) if items else []
    total, healthy, availability = compute_availability(recent)
    http_p95 = latency_percentile_ms(recent, field="http_elapsed_ms", percentile=95.0) if recent else None
    browser_p95 = latency_percentile_ms(recent, field="browser_elapsed_ms", percentile=95.0) if recent else None
    http_slow = None
    if recent and context.http_slow_max is not None:
        http_slow = 0
        for sample in recent:
            latency = sample[_HTTP_INDEX]
            if latency is not None and latency > context.http_slow_max:
                http_slow += 1
    browser_slow = None
    if recent and context.browser_slow_max is not None:
        browser_slow = 0
        for sample in recent:
            latency = sample[_BROWSER_INDEX]
            if latency is not None and latency > context.browser_slow_max:
                browser_slow += 1
    return {
        "availability_24h": {"total": total, "ok": healthy, "ok_pct": availability},
        "latency_24h": {"http_p95_ms": http_p95, "browser_p95_ms": browser_p95},
        "slow_24h": {
            "http_count": http_slow,
            "browser_count": browser_slow,
            "http_threshold_ms": context.http_slow_max,
            "browser_threshold_ms": context.browser_slow_max,
        },
    }


def _domain_summary(domain: str, items: list[Sample], context: _DomainContext) -> MonitorRecord:
    domain_info = context.config_by_domain.get(domain, {})
    group_id = str(domain_info.get("group") or "unconfigured")
    group_info = context.groups_by_id.get(
        group_id,
        {"id": group_id, "label": group_id.replace("-", " ").title(), "description": None, "order": 9999},
    )
    latest, synthetic, api_contract = _latest_summary(domain, items, context.state)
    summary: MonitorRecord = {
        "domain": domain,
        "label": str(domain_info.get("label") or domain),
        "group": group_id,
        "group_label": group_info.get("label"),
        "group_description": group_info.get("description"),
        "group_order": group_info.get("order"),
        "environment": str(domain_info.get("environment") or "unspecified"),
        "kind": str(domain_info.get("kind") or "application"),
        "disabled": bool(domain_info.get("disabled", False)),
        "disabled_reason": domain_info.get("disabled_reason"),
        "disabled_until_ts": domain_info.get("disabled_until_ts"),
        "alert_policy": domain_info.get("alert_policy"),
        "last": latest,
        "streaks": {
            "fail": safe_int(monitor_mapping(context.state.get("fail_streak")).get(domain)) or 0,
            "success": safe_int(monitor_mapping(context.state.get("success_streak")).get(domain)) or 0,
        },
        "synthetic": synthetic,
        "web_vitals": _subcheck(context.state, "web_vitals", domain),
        "api_contract": api_contract,
    }
    summary.update(_window_summary(items, context))
    return summary


def summarize_domains(*, data: MonitorData, now_ts: float) -> MonitorRecords:
    """Return one current and rolling-day summary per configured domain."""
    state = data.state
    history = monitor_mapping(state.get("history"))
    history_by_domain = cast("dict[str, list[Sample]]", history)
    domain_entries = normalize_domain_entries(data.config.get("domains"))
    group_entries = normalize_domain_groups(data.config.get("domain_groups"))
    performance = monitor_mapping(data.config.get("performance"))
    config_by_domain: dict[str, MonitorRecord] = {}
    for entry in domain_entries:
        config_by_domain[str(entry.get("domain") or "")] = entry
    context = _DomainContext(
        state=state,
        config_by_domain=config_by_domain,
        groups_by_id={str(group.get("id") or ""): group for group in group_entries},
        now_ts=float(now_ts),
        http_slow_max=safe_float(performance.get("http_elapsed_ms_max")),
        browser_slow_max=safe_float(performance.get("browser_elapsed_ms_max")),
    )
    if domain_entries:
        configured_values = (entry.get("domain") for entry in domain_entries)
        present_values = filter(None, configured_values)
        domains = list(map(str, present_values))
    else:
        last_ok_domains = monitor_mapping(state.get("last_ok"))
        domains = sorted(set(history_by_domain) | set(last_ok_domains))
    return [_domain_summary(domain, history_by_domain.get(domain, []), context) for domain in domains]
