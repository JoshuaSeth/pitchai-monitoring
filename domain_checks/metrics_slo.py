# Copyright (c) 2026 PitchAI. All rights reserved.
"""PitchAI domain monitoring support for metrics slo."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import TYPE_CHECKING, NamedTuple

from domain_checks.history import (
    compute_availability,
    compute_burn_rate,
    window_samples,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from domain_checks.history import Sample
    from domain_checks.types import JsonValue


class SloBurnViolation(NamedTuple):
    """Represent one sustained SLO burn-rate violation."""

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


@dataclass(frozen=True)
class _SloBurnRule:
    name: str
    short_window_minutes: int
    long_window_minutes: int
    short_burn_rate: float
    long_burn_rate: float
    min_samples_short: int
    min_samples_long: int


def _float_setting(value: JsonValue, default: float) -> float:
    if not isinstance(value, bool | int | float | str):
        return default
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _int_setting(value: JsonValue, default: int) -> int:
    if not isinstance(value, bool | int | float | str):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _coerce_rules(
    raw: list[JsonValue],
    *,
    min_total_samples: int,
) -> list[_SloBurnRule]:
    rules: list[_SloBurnRule] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name_value = item.get("name")
        name = (
            name_value.strip()
            if isinstance(name_value, str) and name_value.strip()
            else "burn"
        )
        rules.append(
            _SloBurnRule(
                name=name,
                short_window_minutes=_int_setting(item.get("short_window_minutes"), 5),
                long_window_minutes=_int_setting(item.get("long_window_minutes"), 60),
                short_burn_rate=_float_setting(item.get("short_burn_rate"), 14.4),
                long_burn_rate=_float_setting(item.get("long_burn_rate"), 6.0),
                min_samples_short=_int_setting(
                    item.get("min_samples_short"),
                    min_total_samples,
                ),
                min_samples_long=_int_setting(
                    item.get("min_samples_long"),
                    min_total_samples,
                ),
            ),
        )
    return rules


def compute_slo_burn_violations(
    *,
    history_by_domain: Mapping[str, list[Sample]],
    now_ts: float,
    slo_target_percent: float,
    burn_rate_rules: list[JsonValue],
    min_total_samples: int = 5,
) -> list[SloBurnViolation]:
    """Compute all configured sustained SLO burn-rate violations.

    Returns:
        Sustained burn-rate violations ordered by domain and rule.
    """
    rules = _coerce_rules(burn_rate_rules, min_total_samples=min_total_samples)
    violations: list[SloBurnViolation] = []
    now = float(now_ts)
    candidates = product(history_by_domain.items(), rules)
    for (domain, items), rule in candidates:
        violation = _evaluate_rule(
            domain,
            items,
            rule,
            now,
            float(slo_target_percent),
        )
        if violation is not None:
            violations.append(violation)

    violations.sort(key=lambda v: (v.domain, v.rule))
    return violations


def _availability_percent(items: list[Sample]) -> float | None:
    _total, _ok, percent = compute_availability(items)
    return float(percent) if percent is not None else None


def _evaluate_rule(
    domain: str,
    items: list[Sample],
    rule: _SloBurnRule,
    now: float,
    target_percent: float,
) -> SloBurnViolation | None:
    if not items or rule.short_window_minutes <= 0 or rule.long_window_minutes <= 0:
        return None
    short_items = window_samples(
        items,
        since_ts=now - (rule.short_window_minutes * 60.0),
    )
    long_items = window_samples(
        items,
        since_ts=now - (rule.long_window_minutes * 60.0),
    )
    if len(short_items) < rule.min_samples_short:
        return None
    if len(long_items) < rule.min_samples_long:
        return None
    short_burn = compute_burn_rate(short_items, slo_target_percent=target_percent)
    long_burn = compute_burn_rate(long_items, slo_target_percent=target_percent)
    if short_burn is None or long_burn is None:
        return None
    if short_burn < rule.short_burn_rate or long_burn < rule.long_burn_rate:
        return None
    return SloBurnViolation(
        domain=domain,
        rule=rule.name,
        short_window_minutes=rule.short_window_minutes,
        long_window_minutes=rule.long_window_minutes,
        short_burn_rate=float(short_burn),
        long_burn_rate=float(long_burn),
        short_availability_percent=_availability_percent(short_items),
        long_availability_percent=_availability_percent(long_items),
        short_total=len(short_items),
        long_total=len(long_items),
    )
