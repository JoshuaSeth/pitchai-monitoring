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
    for entry in domains_cfg:
        if isinstance(entry, str):
            d = entry.strip()
            if not d:
                continue
            out.append({"domain": d, "disabled": False, "disabled_reason": None, "disabled_until_ts": None})
            continue
        if isinstance(entry, dict):
            d = str(entry.get("domain") or "").strip()
            if not d:
                continue
            disabled = bool(entry.get("disabled")) or (entry.get("enabled") is False)

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
                    "disabled": disabled,
                    "disabled_reason": str(entry.get("disabled_reason") or "").strip() or None,
                    "disabled_until_ts": _parse_until(entry.get("disabled_until")),
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

    perf_cfg = cfg.get("performance") if isinstance(cfg.get("performance"), dict) else {}
    http_slow_max = _safe_float(perf_cfg.get("http_elapsed_ms_max"))
    browser_slow_max = _safe_float(perf_cfg.get("browser_elapsed_ms_max"))

    # Include domains we have state for, even if config is missing or incomplete.
    known_domains = set(history_by_domain.keys()) | set((state.get("last_ok") or {}).keys())
    if domains_cfg:
        ordered = [str(it.get("domain") or "") for it in domains_cfg]
        all_domains = [d for d in ordered if d] + sorted(d for d in known_domains if d not in set(ordered))
    else:
        all_domains = sorted(known_domains)

    # Fast lookup for disabled status.
    disabled_map = {str(it.get("domain") or ""): it for it in domains_cfg}

    out: list[dict[str, Any]] = []
    for dom in all_domains:
        items = history_by_domain.get(dom) or []
        last_sample = items[-1] if items else None
        last_ts = _safe_float(last_sample[0]) if isinstance(last_sample, list) and len(last_sample) >= 1 else None
        last_ok = bool(last_sample[1]) if isinstance(last_sample, list) and len(last_sample) >= 2 else bool((state.get("last_ok") or {}).get(dom, True))
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

        disabled_info = disabled_map.get(dom) or {}
        out.append(
            {
                "domain": dom,
                "disabled": bool(disabled_info.get("disabled", False)),
                "disabled_reason": disabled_info.get("disabled_reason"),
                "disabled_until_ts": disabled_info.get("disabled_until_ts"),
                "last": {
                    "ts": last_ts,
                    "ok": bool(last_ok),
                    "http_ms": last_http_ms,
                    "browser_ms": last_browser_ms,
                    "status_code": last_status_code,
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
                    "last_ok": (state.get("synthetic", {}).get("last_ok", {}) or {}).get(dom),
                    "fail_streak": (state.get("synthetic", {}).get("fail_streak", {}) or {}).get(dom),
                    "success_streak": (state.get("synthetic", {}).get("success_streak", {}) or {}).get(dom),
                    "last_run_ts": (state.get("synthetic", {}).get("last_run_ts", {}) or {}).get(dom),
                },
                "web_vitals": {
                    "last_ok": (state.get("web_vitals", {}).get("last_ok", {}) or {}).get(dom),
                    "fail_streak": (state.get("web_vitals", {}).get("fail_streak", {}) or {}).get(dom),
                    "success_streak": (state.get("web_vitals", {}).get("success_streak", {}) or {}).get(dom),
                    "last_run_ts": (state.get("web_vitals", {}).get("last_run_ts", {}) or {}).get(dom),
                },
                "api_contract": {
                    "last_ok": (state.get("api_contract", {}).get("last_ok", {}) or {}).get(dom),
                    "fail_streak": (state.get("api_contract", {}).get("fail_streak", {}) or {}).get(dom),
                    "success_streak": (state.get("api_contract", {}).get("success_streak", {}) or {}).get(dom),
                    "last_run_ts": (state.get("api_contract", {}).get("last_run_ts", {}) or {}).get(dom),
                },
            }
        )
    return out


def summarize_signals(*, data: MonitorData) -> dict[str, Any]:
    s = data.state or {}
    return {
        "browser": {
            "degraded_active": bool(s.get("browser_degraded_active", False)),
            "degraded_first_seen_ts": _safe_float(s.get("browser_degraded_first_seen_ts")),
            "last_notice_ts": _safe_float(s.get("browser_degraded_last_notice_ts")),
            "launch_last_error": s.get("browser_launch_last_error"),
        },
        "host_health": s.get("host_health") or {},
        "host_last_snapshot": s.get("host_last_snapshot") or {},
        "performance": s.get("performance") or {},
        "slo": s.get("slo") or {},
        "red": s.get("red") or {},
        "tls": s.get("tls") or {},
        "dns": s.get("dns") or {},
        "container_health": s.get("container_health") or {},
        "proxy": s.get("proxy") or {},
        "meta": s.get("meta") or {},
    }


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
    down_domains = [d for d in domains if (not d.get("disabled")) and (not bool((d.get("last") or {}).get("ok", True)))]
    degraded_signals = []
    for key in ("host_health", "performance", "slo", "red", "tls", "dns", "container_health", "proxy", "meta"):
        v = signals.get(key) if isinstance(signals.get(key), dict) else {}
        if v and v.get("last_ok") is False:
            degraded_signals.append(key)
    if signals.get("browser", {}).get("degraded_active"):
        degraded_signals.append("browser")

    return {
        "ok": True,
        "generated_at_ts": float(now_ts),
        "state_path": data.state_path,
        "config_path": data.config_path,
        "loaded_at_ts": float(data.loaded_at_ts),
        "error": data.state_error,
        "history_range": {"min_ts": min_ts, "max_ts": max_ts},
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
        "events": state.get("events") if isinstance(state.get("events"), list) else [],
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
