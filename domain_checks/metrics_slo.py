from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain_checks.history import compute_availability, compute_burn_rate, window_samples, Sample


@dataclass(frozen=True)
class SloBurnViolation:
    domain: str
    rule: str
    short_window_minutes: int
    long_window_minutes: int
    short_burn_rate: float
    long_burn_rate: float
    short_availability_percent: float | None
    long_availability_percent: float | None
    short_total: int
    long_total: int


def _coerce_rules(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(item)
    return out


def compute_slo_burn_violations(
    *,
    history_by_domain: dict[str, list[Sample]],
    now_ts: float,
    slo_target_percent: float,
    burn_rate_rules: list[dict[str, Any]],
    min_total_samples: int = 5,
) -> list[SloBurnViolation]:
    rules = _coerce_rules(burn_rate_rules)
    violations: list[SloBurnViolation] = []
    now = float(now_ts)

    for domain, items in history_by_domain.items():
        if not items:
            continue
        for rule in rules:
            name = str(rule.get("name") or "burn").strip() or "burn"
            try:
                short_w = int(rule.get("short_window_minutes") or 5)
                long_w = int(rule.get("long_window_minutes") or 60)
                short_thr = float(rule.get("short_burn_rate") or 14.4)
                long_thr = float(rule.get("long_burn_rate") or 6.0)
            except Exception:
                continue
            if short_w <= 0 or long_w <= 0:
                continue

            short_items = window_samples(items, since_ts=now - (short_w * 60.0))
            long_items = window_samples(items, since_ts=now - (long_w * 60.0))
            if len(short_items) < int(rule.get("min_samples_short") or min_total_samples):
                continue
            if len(long_items) < int(rule.get("min_samples_long") or min_total_samples):
                continue

            short_burn = compute_burn_rate(short_items, slo_target_percent=float(slo_target_percent))
            long_burn = compute_burn_rate(long_items, slo_target_percent=float(slo_target_percent))
            if short_burn is None or long_burn is None:
                continue

            if short_burn >= short_thr and long_burn >= long_thr:
                _s_total, _s_ok, s_ok_pct = compute_availability(short_items)
                _l_total, _l_ok, l_ok_pct = compute_availability(long_items)
                violations.append(
                    SloBurnViolation(
                        domain=domain,
                        rule=name,
                        short_window_minutes=short_w,
                        long_window_minutes=long_w,
                        short_burn_rate=float(short_burn),
                        long_burn_rate=float(long_burn),
                        short_availability_percent=(float(s_ok_pct) if s_ok_pct is not None else None),
                        long_availability_percent=(float(l_ok_pct) if l_ok_pct is not None else None),
                        short_total=len(short_items),
                        long_total=len(long_items),
                    )
                )

    violations.sort(key=lambda v: (v.domain, v.rule))
    return violations

