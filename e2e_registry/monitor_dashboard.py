from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from domain_checks.history import (
    Sample,
    coerce_history,
    compute_availability,
    latency_percentile_ms,
    window_samples,
)
from domain_checks.inventory import parse_domain_alert_policy


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _safe_timestamp(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        return timestamp if timestamp > 0 else None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        timestamp = float(raw)
    except ValueError:
        iso_value = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            parsed = datetime.fromisoformat(iso_value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        timestamp = parsed.timestamp()
    return timestamp if timestamp > 0 else None


def _downsample(items: list[Any], *, max_points: int) -> list[Any]:
    max_points = max(1, int(max_points))
    n = len(items)
    if n <= max_points:
        return items
    step = int(math.ceil(n / float(max_points)))
    if step <= 1:
        return items
    out = items[::step]
    # Always include last point.
    if out and out[-1] is not items[-1]:
        out.append(items[-1])
    return out


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_domain_entries(domains_cfg: Any) -> list[dict[str, Any]]:
    """
    Minimal replica of domain_checks.main._normalize_domain_entries (without disabled_until parsing).
    Used for dashboard display only.
    """
    if not isinstance(domains_cfg, list):
        return []
    out: list[dict[str, Any]] = []
    for index, entry in enumerate(domains_cfg):
        if isinstance(entry, str):
            d = entry.strip()
            if not d:
                continue
            out.append(
                {
                    "domain": d,
                    "label": d,
                    "group": "ungrouped",
                    "environment": "unspecified",
                    "kind": "application",
                    "disabled": False,
                    "disabled_reason": None,
                    "disabled_until_ts": None,
                    "alert_policy": parse_domain_alert_policy(entry).to_dashboard_dict(),
                }
            )
            continue
        if isinstance(entry, dict):
            d = str(entry.get("domain") or "").strip()
            if not d:
                continue
            disabled = bool(entry.get("disabled")) or (entry.get("enabled") is False)
            alert_policy = parse_domain_alert_policy(entry, path=f"domains[{index}]")

            def _parse_until(value: Any) -> float | None:
                if value is None:
                    return None
                if isinstance(value, (int, float)):
                    ts = float(value)
                    return ts if ts > 0 else None
                s = str(value or "").strip()
                if not s:
                    return None
                try:
                    ts = float(s)
                    return ts if ts > 0 else None
                except Exception:
                    pass
                s_iso = s[:-1] + "+00:00" if s.endswith("Z") else s
                try:
                    dt = datetime.fromisoformat(s_iso)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt.timestamp()
                except ValueError:
                    d2 = date.fromisoformat(s)
                    dt = datetime(d2.year, d2.month, d2.day, tzinfo=timezone.utc)
                    return dt.timestamp()

            out.append(
                {
                    "domain": d,
                    "label": str(entry.get("label") or d).strip(),
                    "group": str(entry.get("group") or "ungrouped").strip(),
                    "environment": str(entry.get("environment") or "unspecified").strip(),
                    "kind": str(entry.get("kind") or "application").strip(),
                    "disabled": disabled,
                    "disabled_reason": str(entry.get("disabled_reason") or "").strip() or None,
                    "disabled_until_ts": _parse_until(entry.get("disabled_until")),
                    "alert_policy": alert_policy.to_dashboard_dict(),
                }
            )
            continue
    # De-dupe while preserving order.
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for it in out:
        d = str(it.get("domain") or "").strip()
        if not d or d in seen:
            continue
        seen.add(d)
        deduped.append(it)
    return deduped


def _normalize_domain_groups(groups_cfg: Any) -> list[dict[str, Any]]:
    if not isinstance(groups_cfg, dict):
        return []
    groups: list[dict[str, Any]] = []
    for group_id, raw in groups_cfg.items():
        cleaned_id = str(group_id or "").strip()
        if not cleaned_id or not isinstance(raw, dict):
            continue
        try:
            order = int(raw.get("order", 1000))
        except (TypeError, ValueError):
            order = 1000
        groups.append(
            {
                "id": cleaned_id,
                "label": str(raw.get("label") or cleaned_id.replace("-", " ").title()).strip(),
                "description": str(raw.get("description") or "").strip() or None,
                "order": order,
            }
        )
    return sorted(groups, key=lambda group: (int(group["order"]), str(group["label"]).lower()))


@dataclass(frozen=True)
class MonitorData:
    state: dict[str, Any]
    config: dict[str, Any]
    state_path: str
    config_path: str
    loaded_at_ts: float
    state_error: str | None


def load_monitor_data(*, state_path: str, config_path: str) -> MonitorData:
    sp = Path(str(state_path or "").strip())
    cp = Path(str(config_path or "").strip())
    state_raw = _load_json(sp) if str(sp) else {}
    cfg_raw = _load_yaml(cp) if str(cp) else {}

    history = coerce_history(state_raw.get("history"))
    state_raw["history"] = history

    state_error = None
    if not state_raw:
        state_error = f"missing_or_invalid_state: {sp}"
    if not cfg_raw:
        # Keep dashboard usable even if config missing; just surface the message.
        state_error = (state_error + "; " if state_error else "") + f"missing_or_invalid_config: {cp}"

    return MonitorData(
        state=state_raw,
        config=cfg_raw,
        state_path=str(sp),
        config_path=str(cp),
        loaded_at_ts=time.time(),
        state_error=state_error,
    )


def _parse_range_to_seconds(rng: str) -> float:
    s = str(rng or "").strip().lower()
    if s in {"6h", "6hr", "6hrs"}:
        return 6 * 3600.0
    if s in {"12h", "12hr", "12hrs"}:
        return 12 * 3600.0
    if s in {"24h", "1d", "day"}:
        return 24 * 3600.0
    if s in {"48h", "2d"}:
        return 48 * 3600.0
    if s in {"7d", "week"}:
        return 7 * 86400.0
    if s in {"14d", "2w", "two_weeks"}:
        return 14 * 86400.0
    if s in {"30d", "month"}:
        return 30 * 86400.0
    # default
    return 24 * 3600.0


def _history_range_utc(history_by_domain: dict[str, list[Sample]]) -> tuple[float | None, float | None]:
    min_ts = None
    max_ts = None
    for _dom, items in history_by_domain.items():
        if not items:
            continue
        try:
            t0 = float(items[0][0])
            t1 = float(items[-1][0])
        except Exception:
            continue
        min_ts = t0 if min_ts is None else min(min_ts, t0)
        max_ts = t1 if max_ts is None else max(max_ts, t1)
    return min_ts, max_ts


def summarize_domains(
    *,
    data: MonitorData,
    now_ts: float,
) -> list[dict[str, Any]]:
    cfg = data.config or {}
    state = data.state or {}
    history_by_domain: dict[str, list[Sample]] = state.get("history") if isinstance(state.get("history"), dict) else {}
    domains_cfg = _normalize_domain_entries(cfg.get("domains"))
    groups_cfg = _normalize_domain_groups(cfg.get("domain_groups"))
    groups_by_id = {str(group["id"]): group for group in groups_cfg}

    perf_cfg = cfg.get("performance") if isinstance(cfg.get("performance"), dict) else {}
    http_slow_max = _safe_float(perf_cfg.get("http_elapsed_ms_max"))
    browser_slow_max = _safe_float(perf_cfg.get("browser_elapsed_ms_max"))

    # The configured inventory is authoritative. Historical state for a removed
    # hostname must not silently turn that hostname back into a live check.
    known_domains = set(history_by_domain.keys()) | set((state.get("last_ok") or {}).keys())
    if domains_cfg:
        ordered = [str(it.get("domain") or "") for it in domains_cfg]
        all_domains = [domain for domain in ordered if domain]
    else:
        all_domains = sorted(known_domains)

    # Fast lookup for disabled status.
    config_map = {str(it.get("domain") or ""): it for it in domains_cfg}

    out: list[dict[str, Any]] = []
    for dom in all_domains:
        items = history_by_domain.get(dom) or []
        last_sample = items[-1] if items else None
        last_ts = _safe_float(last_sample[0]) if isinstance(last_sample, list) and len(last_sample) >= 1 else None
        last_ok_state = state.get("last_ok") if isinstance(state.get("last_ok"), dict) else {}
        if isinstance(last_sample, list) and len(last_sample) >= 2:
            last_ok: bool | None = bool(last_sample[1])
        elif dom in last_ok_state:
            last_ok = bool(last_ok_state.get(dom))
        else:
            last_ok = None
        last_http_ms = _safe_float(last_sample[2]) if isinstance(last_sample, list) and len(last_sample) >= 3 else None
        last_browser_ms = _safe_float(last_sample[3]) if isinstance(last_sample, list) and len(last_sample) >= 4 else None
        last_status_code = _safe_int(last_sample[4]) if isinstance(last_sample, list) and len(last_sample) >= 5 else None

        # 24h window stats for summary.
        w24 = window_samples(items, since_ts=float(now_ts) - 86400.0) if items else []
        total24, ok24, ok_pct24 = compute_availability(w24)
        http_p95_24 = latency_percentile_ms(w24, field="http_elapsed_ms", percentile=95.0) if w24 else None
        browser_p95_24 = latency_percentile_ms(w24, field="browser_elapsed_ms", percentile=95.0) if w24 else None

        http_slow_24 = None
        browser_slow_24 = None
        if w24 and http_slow_max is not None:
            http_slow_24 = sum(1 for s in w24 if len(s) >= 3 and s[2] is not None and float(s[2]) > float(http_slow_max))
        if w24 and browser_slow_max is not None:
            browser_slow_24 = sum(1 for s in w24 if len(s) >= 4 and s[3] is not None and float(s[3]) > float(browser_slow_max))

        synthetic_last_ok = (state.get("synthetic", {}).get("last_ok", {}) or {}).get(dom)
        api_contract_last_ok = (state.get("api_contract", {}).get("last_ok", {}) or {}).get(dom)
        synthetic_last_run_ts = _safe_timestamp(
            (state.get("synthetic", {}).get("last_run_ts", {}) or {}).get(dom)
        )
        api_contract_last_run_ts = _safe_timestamp(
            (state.get("api_contract", {}).get("last_run_ts", {}) or {}).get(dom)
        )
        failure_sources: list[str] = []
        if last_ok is False:
            failure_sources.append("primary")
        if api_contract_last_ok is False:
            failure_sources.append("api_contract")
        if synthetic_last_ok is False:
            failure_sources.append("synthetic")
        effective_last_ok = False if failure_sources else last_ok
        effective_timestamps = [
            timestamp
            for timestamp in (last_ts, api_contract_last_run_ts, synthetic_last_run_ts)
            if timestamp is not None
        ]
        effective_last_ts = max(effective_timestamps) if effective_timestamps else None
        effective_status_code = last_status_code if last_ok is False or not failure_sources else None

        domain_info = config_map.get(dom) or {}
        group_id = str(domain_info.get("group") or "unconfigured")
        group_info = groups_by_id.get(group_id) or {
            "id": group_id,
            "label": group_id.replace("-", " ").title(),
            "description": None,
            "order": 9999,
        }
        out.append(
            {
                "domain": dom,
                "label": str(domain_info.get("label") or dom),
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
                "last": {
                    "ts": effective_last_ts,
                    "primary_ts": last_ts,
                    "ok": effective_last_ok,
                    "primary_ok": last_ok,
                    "failure_sources": failure_sources,
                    "http_ms": last_http_ms,
                    "browser_ms": last_browser_ms,
                    "status_code": effective_status_code,
                    "primary_status_code": last_status_code,
                },
                "streaks": {
                    "fail": int((state.get("fail_streak") or {}).get(dom, 0)),
                    "success": int((state.get("success_streak") or {}).get(dom, 0)),
                },
                "availability_24h": {
                    "total": int(total24),
                    "ok": int(ok24),
                    "ok_pct": ok_pct24,
                },
                "latency_24h": {
                    "http_p95_ms": http_p95_24,
                    "browser_p95_ms": browser_p95_24,
                },
                "slow_24h": {
                    "http_count": http_slow_24,
                    "browser_count": browser_slow_24,
                    "http_threshold_ms": http_slow_max,
                    "browser_threshold_ms": browser_slow_max,
                },
                "synthetic": {
                    "last_ok": synthetic_last_ok,
                    "fail_streak": (state.get("synthetic", {}).get("fail_streak", {}) or {}).get(dom),
                    "success_streak": (state.get("synthetic", {}).get("success_streak", {}) or {}).get(dom),
                    "last_run_ts": synthetic_last_run_ts,
                },
                "web_vitals": {
                    "last_ok": (state.get("web_vitals", {}).get("last_ok", {}) or {}).get(dom),
                    "fail_streak": (state.get("web_vitals", {}).get("fail_streak", {}) or {}).get(dom),
                    "success_streak": (state.get("web_vitals", {}).get("success_streak", {}) or {}).get(dom),
                    "last_run_ts": (state.get("web_vitals", {}).get("last_run_ts", {}) or {}).get(dom),
                },
                "api_contract": {
                    "last_ok": api_contract_last_ok,
                    "fail_streak": (state.get("api_contract", {}).get("fail_streak", {}) or {}).get(dom),
                    "success_streak": (state.get("api_contract", {}).get("success_streak", {}) or {}).get(dom),
                    "last_run_ts": api_contract_last_run_ts,
                },
            }
        )
    return out


def summarize_domain_groups(*, domains: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    configured_groups = _normalize_domain_groups(config.get("domain_groups"))
    definitions = {str(group["id"]): dict(group) for group in configured_groups}
    for domain in domains:
        group_id = str(domain.get("group") or "unconfigured")
        definitions.setdefault(
            group_id,
            {
                "id": group_id,
                "label": str(domain.get("group_label") or group_id.replace("-", " ").title()),
                "description": domain.get("group_description"),
                "order": domain.get("group_order") or 9999,
            },
        )

    summaries: list[dict[str, Any]] = []
    for group_id, definition in definitions.items():
        members = [domain for domain in domains if str(domain.get("group") or "unconfigured") == group_id]
        if not members:
            continue
        health = _summarize_service_health(members)
        if health["alertable_down"]:
            status = "attention"
        elif health["expected_down"]:
            status = "expected"
        elif health["unknown"]:
            status = "unknown"
        else:
            status = "healthy"
        summaries.append({**definition, **health, "total": len(members), "status": status})
    return sorted(summaries, key=lambda group: (int(group.get("order") or 9999), str(group.get("label") or "").lower()))


def summarize_signals(*, data: MonitorData) -> dict[str, Any]:
    s = data.state or {}
    signal_history = s.get("signal_history") if isinstance(s.get("signal_history"), dict) else {}
    signals = {
        "browser": {
            "degraded_active": bool(s.get("browser_degraded_active", False)),
            "degraded_first_seen_ts": _safe_float(s.get("browser_degraded_first_seen_ts")),
            "last_notice_ts": _safe_float(s.get("browser_degraded_last_notice_ts")),
            "launch_last_error": s.get("browser_launch_last_error"),
        },
        "host_health": dict(s.get("host_health")) if isinstance(s.get("host_health"), dict) else {},
        "host_last_snapshot": dict(s.get("host_last_snapshot")) if isinstance(s.get("host_last_snapshot"), dict) else {},
        "performance": dict(s.get("performance")) if isinstance(s.get("performance"), dict) else {},
        "slo": dict(s.get("slo")) if isinstance(s.get("slo"), dict) else {},
        "red": dict(s.get("red")) if isinstance(s.get("red"), dict) else {},
        "tls": dict(s.get("tls")) if isinstance(s.get("tls"), dict) else {},
        "dns": dict(s.get("dns")) if isinstance(s.get("dns"), dict) else {},
        "container_health": dict(s.get("container_health")) if isinstance(s.get("container_health"), dict) else {},
        "proxy": dict(s.get("proxy")) if isinstance(s.get("proxy"), dict) else {},
        "meta": dict(s.get("meta")) if isinstance(s.get("meta"), dict) else {},
    }
    for key, signal in signals.items():
        if key in {"browser", "host_last_snapshot"} or not isinstance(signal, dict):
            continue
        history = signal_history.get(key) if isinstance(signal_history.get(key), list) else []
        if history and isinstance(history[-1], list) and history[-1]:
            signal["observed_at_ts"] = _safe_timestamp(history[-1][0])
    return signals


def _event_kind_is_problem(kind: str) -> bool:
    normalized = str(kind or "").strip().lower()
    return normalized.endswith(("_down", "_degraded", "_failed", "_failure", "_error", "_unhealthy"))


def _event_kind_is_recovery(kind: str) -> bool:
    normalized = str(kind or "").strip().lower()
    return normalized.endswith(("_up", "_recovered", "_healthy"))


def _signal_display_name(signal: str) -> str:
    return {
        "host_health": "Host health",
        "performance": "Performance",
        "slo": "SLO",
        "red": "RED metrics",
        "tls": "TLS",
        "dns": "DNS",
        "container_health": "Container health",
        "proxy": "Reverse proxy",
        "meta": "Monitor integrity",
        "browser": "Browser checks",
    }.get(signal, signal.replace("_", " ").title())


def _summarize_freshness(
    *,
    data: MonitorData,
    now_ts: float,
    history_max_ts: float | None,
) -> dict[str, Any]:
    state_updated_at_ts = _safe_timestamp((data.state or {}).get("updated_at"))
    source = "state.updated_at"
    if state_updated_at_ts is None:
        state_updated_at_ts = history_max_ts
        source = "history.max_ts" if history_max_ts is not None else "unavailable"

    interval_seconds = _safe_int((data.config or {}).get("interval_seconds"))
    if interval_seconds is None or interval_seconds <= 0:
        interval_seconds = 60
    stale_after_seconds = max(180, interval_seconds * 3)

    if state_updated_at_ts is None:
        return {
            "status": "unknown",
            "state_updated_at_ts": None,
            "age_seconds": None,
            "interval_seconds": interval_seconds,
            "stale_after_seconds": stale_after_seconds,
            "source": source,
        }

    age_seconds = max(0.0, float(now_ts) - state_updated_at_ts)
    return {
        "status": "fresh" if age_seconds <= stale_after_seconds else "stale",
        "state_updated_at_ts": state_updated_at_ts,
        "age_seconds": age_seconds,
        "interval_seconds": interval_seconds,
        "stale_after_seconds": stale_after_seconds,
        "source": source,
    }


def _summarize_e2e(e2e_status_summary: dict[str, Any] | None, *, now_ts: float) -> dict[str, Any]:
    if not isinstance(e2e_status_summary, dict) or e2e_status_summary.get("ok") is not True:
        return {
            "status": "unavailable",
            "total_tests": None,
            "passing_tests": None,
            "failing_tests": None,
            "disabled_tests": None,
            "latest_run_at_ts": None,
            "latest_run_age_seconds": None,
            "problems": [],
        }

    tests = e2e_status_summary.get("tests") if isinstance(e2e_status_summary.get("tests"), list) else []
    enabled_tests = [test for test in tests if isinstance(test, dict) and int(test.get("enabled", 1) or 0) == 1]
    problems: list[dict[str, Any]] = []
    latest_run_at_ts = None
    for test in enabled_tests:
        finished_at_ts = _safe_timestamp(test.get("last_finished_at_ts"))
        if finished_at_ts is not None:
            latest_run_at_ts = (
                finished_at_ts if latest_run_at_ts is None else max(latest_run_at_ts, finished_at_ts)
            )
        try:
            effective_ok = int(test.get("effective_ok", 1) if test.get("effective_ok") is not None else 1)
        except (TypeError, ValueError):
            effective_ok = 1
        if effective_ok != 0:
            continue
        problems.append(
            {
                "test_id": str(test.get("test_id") or ""),
                "test_name": str(test.get("test_name") or "Unnamed E2E test"),
                "base_url": str(test.get("base_url") or ""),
                "fail_streak": _safe_int(test.get("fail_streak")) or 0,
                "last_status": str(test.get("last_status") or "unknown"),
                "last_finished_at_ts": finished_at_ts,
            }
        )

    total_tests = len(enabled_tests)
    failing_tests = len(problems)
    passing_tests = max(0, total_tests - failing_tests)
    latest_run_age_seconds = (
        max(0.0, float(now_ts) - latest_run_at_ts) if latest_run_at_ts is not None else None
    )
    return {
        "status": "attention" if failing_tests else "healthy",
        "total_tests": total_tests,
        "passing_tests": passing_tests,
        "failing_tests": failing_tests,
        "disabled_tests": max(0, len(tests) - total_tests),
        "latest_run_at_ts": latest_run_at_ts,
        "latest_run_age_seconds": latest_run_age_seconds,
        "problems": problems,
    }


def _summarize_service_health(domains: list[dict[str, Any]]) -> dict[str, int]:
    enabled_domains = [domain for domain in domains if not bool(domain.get("disabled"))]
    down_domains = [domain for domain in enabled_domains if (domain.get("last") or {}).get("ok") is False]
    unknown_domains = [domain for domain in enabled_domains if (domain.get("last") or {}).get("ok") is None]
    expected_down = [
        domain
        for domain in down_domains
        if (domain.get("alert_policy") or {}).get("telegram_enabled") is False
    ]
    return {
        "enabled": len(enabled_domains),
        "healthy": len(enabled_domains) - len(down_domains) - len(unknown_domains),
        "down": len(down_domains),
        "alertable_down": len(down_domains) - len(expected_down),
        "expected_down": len(expected_down),
        "unknown": len(unknown_domains),
        "disabled": len(domains) - len(enabled_domains),
    }


def _summarize_daily_status(
    *,
    domains: list[dict[str, Any]],
    events: list[dict[str, Any]],
    open_problem_count: int,
    now_ts: float,
) -> dict[str, Any]:
    observations = 0
    successful_observations = 0
    for domain in domains:
        if bool(domain.get("disabled")):
            continue
        availability = domain.get("availability_24h") if isinstance(domain.get("availability_24h"), dict) else {}
        observations += _safe_int(availability.get("total")) or 0
        successful_observations += _safe_int(availability.get("ok")) or 0

    availability_pct = (
        (successful_observations / observations) * 100.0 if observations > 0 else None
    )
    since_ts = float(now_ts) - 86400.0
    daily_events = []
    for event in events:
        event_ts = _safe_timestamp(event.get("ts"))
        if event_ts is not None and since_ts <= event_ts <= float(now_ts):
            daily_events.append(event)

    problem_events = [
        event
        for event in daily_events
        if _event_kind_is_problem(str(event.get("kind") or ""))
    ]
    recovery_events = [
        event
        for event in daily_events
        if _event_kind_is_recovery(str(event.get("kind") or ""))
    ]
    latest_event_at_ts = None
    for event in daily_events:
        event_ts = _safe_timestamp(event.get("ts"))
        if event_ts is not None:
            latest_event_at_ts = event_ts if latest_event_at_ts is None else max(latest_event_at_ts, event_ts)

    if observations == 0:
        status = "unknown"
    elif open_problem_count > 0:
        status = "attention"
    else:
        status = "healthy"
    return {
        "period_seconds": 86400,
        "status": status,
        "observations": observations,
        "successful_observations": successful_observations,
        "availability_pct": availability_pct,
        "problem_events": len(problem_events),
        "recoveries": len(recovery_events),
        "latest_event_at_ts": latest_event_at_ts,
    }


def _build_incidents(
    *,
    down_domains: list[dict[str, Any]],
    unknown_domains: list[dict[str, Any]],
    degraded_signals: list[str],
    freshness: dict[str, Any],
    e2e: dict[str, Any],
    signals: dict[str, Any],
) -> list[dict[str, Any]]:
    incidents: list[dict[str, Any]] = []
    if freshness.get("status") in {"stale", "unknown"}:
        incidents.append(
            {
                "kind": "monitor_freshness",
                "severity": "critical" if freshness.get("status") == "stale" else "warning",
                "title": "Monitoring state is stale" if freshness.get("status") == "stale" else "Monitoring freshness is unavailable",
                "detail": "The minute monitor has not produced a current state snapshot.",
                "observed_at_ts": freshness.get("state_updated_at_ts"),
            }
        )
    for domain in down_domains:
        last = domain.get("last") if isinstance(domain.get("last"), dict) else {}
        alert_policy = (
            domain.get("alert_policy") if isinstance(domain.get("alert_policy"), dict) else {}
        )
        telegram_enabled = alert_policy.get("telegram_enabled") is not False
        policy_reason = str(alert_policy.get("reason") or "").strip()
        group_label = str(domain.get("group_label") or "Unconfigured")
        failure_sources = [str(source) for source in (last.get("failure_sources") or [])]
        source_labels = {
            "primary": "page/readiness check",
            "api_contract": "API/service subcheck",
            "synthetic": "end-to-end transaction",
        }
        failing_checks = ", ".join(source_labels.get(source, source) for source in failure_sources)
        failure_streaks = [int((domain.get("streaks") or {}).get("fail", 0))]
        if "api_contract" in failure_sources:
            failure_streaks.append(int((domain.get("api_contract") or {}).get("fail_streak") or 0))
        if "synthetic" in failure_sources:
            failure_streaks.append(int((domain.get("synthetic") or {}).get("fail_streak") or 0))
        detail = (
            f"{group_label} · {failing_checks or 'health check'} is down after "
            f"{max(failure_streaks)} failing cycles."
        )
        if not telegram_enabled:
            detail += " Expected/dashboard-only status; no Telegram alert is routed."
            if policy_reason:
                detail += f" {policy_reason}"
        incidents.append(
            {
                "kind": "domain_down",
                "severity": "critical" if telegram_enabled else "expected",
                "title": (
                    f"{domain.get('domain')} is down"
                    if telegram_enabled
                    else f"{domain.get('domain')} is down — expected / dashboard only"
                ),
                "detail": detail,
                "domain": domain.get("domain"),
                "group": domain.get("group"),
                "group_label": group_label,
                "status_code": last.get("status_code"),
                "observed_at_ts": last.get("ts"),
                "telegram_alert": telegram_enabled,
                "expected": not telegram_enabled,
            }
        )
    for domain in unknown_domains:
        group_label = str(domain.get("group_label") or "Unconfigured")
        alert_policy = (
            domain.get("alert_policy") if isinstance(domain.get("alert_policy"), dict) else {}
        )
        telegram_enabled = alert_policy.get("telegram_enabled") is not False
        incidents.append(
            {
                "kind": "domain_unknown",
                "severity": "warning" if telegram_enabled else "expected",
                "title": (
                    f"{domain.get('domain')} has no current result"
                    if telegram_enabled
                    else f"{domain.get('domain')} has no current result — dashboard only"
                ),
                "detail": (
                    f"{group_label} · the domain is enabled but has not produced a health result."
                    + (" No Telegram alert is routed by policy." if not telegram_enabled else "")
                ),
                "domain": domain.get("domain"),
                "group": domain.get("group"),
                "group_label": group_label,
                "observed_at_ts": None,
                "telegram_alert": telegram_enabled,
                "expected": not telegram_enabled,
            }
        )
    for signal in degraded_signals:
        signal_state = signals.get(signal) if isinstance(signals.get(signal), dict) else {}
        failure_count = _safe_int(signal_state.get("fail_streak"))
        detail = "The latest debounced global signal is not healthy."
        if failure_count is not None:
            detail = f"The signal has failed {failure_count:,} consecutive monitor cycles."
        incidents.append(
            {
                "kind": "signal_degraded",
                "severity": "warning",
                "title": f"{_signal_display_name(signal)} is degraded",
                "detail": detail,
                "signal": signal,
                "observed_at_ts": signal_state.get("observed_at_ts"),
            }
        )
    for problem in e2e.get("problems") or []:
        incidents.append(
            {
                "kind": "e2e_failure",
                "severity": "warning",
                "title": f"E2E: {problem.get('test_name')}",
                "detail": f"{problem.get('base_url')} · {int(problem.get('fail_streak') or 0)} effective failures",
                "test_id": problem.get("test_id"),
                "observed_at_ts": problem.get("last_finished_at_ts"),
            }
        )
    return incidents


def build_dashboard_summary(
    *,
    data: MonitorData,
    now_ts: float,
    e2e_status_summary: dict[str, Any] | None,
    e2e_dispatch_runs: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    state = data.state or {}
    history_by_domain: dict[str, list[Sample]] = state.get("history") if isinstance(state.get("history"), dict) else {}
    min_ts, max_ts = _history_range_utc(history_by_domain)
    domains = summarize_domains(data=data, now_ts=float(now_ts))
    signals = summarize_signals(data=data)

    # Count warnings.
    down_domains = [
        domain
        for domain in domains
        if not domain.get("disabled") and (domain.get("last") or {}).get("ok") is False
    ]
    unknown_domains = [
        domain
        for domain in domains
        if not domain.get("disabled") and (domain.get("last") or {}).get("ok") is None
    ]
    degraded_signals = []
    for key in ("host_health", "performance", "slo", "red", "tls", "dns", "container_health", "proxy", "meta"):
        v = signals.get(key) if isinstance(signals.get(key), dict) else {}
        if v and v.get("last_ok") is False:
            degraded_signals.append(key)
    if signals.get("browser", {}).get("degraded_active"):
        degraded_signals.append("browser")

    events = state.get("events") if isinstance(state.get("events"), list) else []
    normalized_events = [event for event in events if isinstance(event, dict)]
    freshness = _summarize_freshness(data=data, now_ts=float(now_ts), history_max_ts=max_ts)
    service_health = _summarize_service_health(domains)
    domain_groups = summarize_domain_groups(domains=domains, config=data.config or {})
    retired_cfg = data.config.get("retired_domains") if isinstance(data.config.get("retired_domains"), list) else []
    inventory_cfg = data.config.get("inventory") if isinstance(data.config.get("inventory"), dict) else {}
    configured_domains = {
        str(entry.get("domain") or "")
        for entry in _normalize_domain_entries(data.config.get("domains"))
        if str(entry.get("domain") or "")
    }
    state_domains = set(history_by_domain.keys()) | set((state.get("last_ok") or {}).keys())
    e2e = _summarize_e2e(e2e_status_summary, now_ts=float(now_ts))
    incidents = _build_incidents(
        down_domains=down_domains,
        unknown_domains=unknown_domains,
        degraded_signals=degraded_signals,
        freshness=freshness,
        e2e=e2e,
        signals=signals,
    )
    daily_status = _summarize_daily_status(
        domains=domains,
        events=normalized_events,
        open_problem_count=len(incidents),
        now_ts=float(now_ts),
    )

    return {
        "ok": True,
        "generated_at_ts": float(now_ts),
        "state_path": data.state_path,
        "config_path": data.config_path,
        "loaded_at_ts": float(data.loaded_at_ts),
        "error": data.state_error,
        "history_range": {"min_ts": min_ts, "max_ts": max_ts},
        "freshness": freshness,
        "service_health": service_health,
        "domain_groups": domain_groups,
        "inventory": {
            "version": inventory_cfg.get("version"),
            "reviewed_at": inventory_cfg.get("reviewed_at"),
            "active_domains": len(domains),
            "groups": len(domain_groups),
            "retired_domains": len(retired_cfg),
            "orphaned_state_domains": len(state_domains - configured_domains),
        },
        "e2e": e2e,
        "incidents": incidents,
        "daily_status": daily_status,
        "domains": domains,
        "signals": signals,
        "warnings": {
            "down_domains": [d.get("domain") for d in down_domains],
            "degraded_signals": degraded_signals,
        },
        "dispatch": {
            "last_by_key": state.get("dispatch_last") if isinstance(state.get("dispatch_last"), dict) else {},
            "recent": state.get("dispatch_history") if isinstance(state.get("dispatch_history"), list) else [],
        },
        "events": normalized_events,
        "external_e2e": e2e_status_summary,
        "e2e_registry_dispatch": e2e_dispatch_runs or [],
    }


def domain_timeseries(
    *,
    data: MonitorData,
    domain: str,
    since_ts: float,
    until_ts: float,
    max_points: int,
) -> dict[str, Any]:
    state = data.state or {}
    history_by_domain: dict[str, list[Sample]] = state.get("history") if isinstance(state.get("history"), dict) else {}
    items = history_by_domain.get(domain) or []
    s = []
    for it in items:
        if not isinstance(it, list) or len(it) < 2:
            continue
        try:
            ts = float(it[0])
        except Exception:
            continue
        if ts < float(since_ts) or ts > float(until_ts):
            continue
        s.append(it)

    s = _downsample(s, max_points=max_points)
    out = {
        "ok": True,
        "domain": domain,
        "since_ts": float(since_ts),
        "until_ts": float(until_ts),
        "samples": [
            {
                "ts": _safe_float(it[0]) if len(it) >= 1 else None,
                "ok": bool(it[1]) if len(it) >= 2 else None,
                "http_ms": _safe_float(it[2]) if len(it) >= 3 else None,
                "browser_ms": _safe_float(it[3]) if len(it) >= 4 else None,
                "status_code": _safe_int(it[4]) if len(it) >= 5 else None,
            }
            for it in s
        ],
    }
    return out


def signal_timeseries(
    *,
    data: MonitorData,
    signal: str,
    since_ts: float,
    until_ts: float,
    max_points: int,
) -> dict[str, Any]:
    state = data.state or {}
    sh = state.get("signal_history") if isinstance(state.get("signal_history"), dict) else {}
    items = sh.get(signal) if isinstance(sh.get(signal), list) else []

    s: list[list[Any]] = []
    for it in items:
        if not isinstance(it, list) or not it:
            continue
        try:
            ts = float(it[0])
        except Exception:
            continue
        if ts < float(since_ts) or ts > float(until_ts):
            continue
        s.append(it)

    s = _downsample(s, max_points=max_points)
    return {"ok": True, "signal": signal, "since_ts": float(since_ts), "until_ts": float(until_ts), "samples": s}


def resolve_range(*, now_ts: float, range_label: str) -> tuple[float, float]:
    dur = _parse_range_to_seconds(range_label)
    until_ts = float(now_ts)
    return until_ts - dur, until_ts
