# Copyright (c) 2026 PitchAI. All rights reserved.
"""Evaluate configured short and long burn windows over retained history."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from operator import attrgetter
from typing import TYPE_CHECKING

from .cycle_values import required_float, required_int
from .history import compute_availability, compute_burn_rate, window_samples

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject, JsonValue
    from .history_decode import Sample


@dataclass(frozen=True)
class SloRuleWindow:
    """Domain/rule identity and its two original window lengths."""

    domain: str
    rule: str
    short_window_minutes: int
    long_window_minutes: int


@dataclass(frozen=True)
class SloBurnViolation(SloRuleWindow):
    """Existing ordered outcome, retaining the original constructor field order."""
    short_burn_rate: float
    long_burn_rate: float
    short_availability_percent: float | None
    long_availability_percent: float | None
    short_total: int
    long_total: int


@dataclass(frozen=True)
class BurnRule:
    """Decoded numeric fields; explicit zero retains the original default rule."""

    name: str
    short_window: int
    long_window: int
    short_threshold: float
    long_threshold: float

    @classmethod
    def parse(cls, raw: JsonObject) -> BurnRule | None:
        """Read numeric rule fields without changing malformed-rule omission.

        Returns:
            None for invalid/nonpositive windows, otherwise the existing rule.
        """
        name = str(raw.get("name") or "burn").strip() or "burn"
        with suppress(TypeError, ValueError, OverflowError):
            short = required_int(raw.get("short_window_minutes") or 5)
            long = required_int(raw.get("long_window_minutes") or 60)
            short_threshold = required_float(raw.get("short_burn_rate") or 14.4)
            long_threshold = required_float(raw.get("long_burn_rate") or 6.0)
            if short > 0 and long > 0:
                return cls(name, short, long, short_threshold, long_threshold)
        return None

    def windows(self, samples: list[Sample], now: float) -> tuple[list[Sample], list[Sample]]:
        """Return both original windows, including samples at cutoff equality."""
        return (window_samples(samples, since_ts=now - self.short_window * 60.0),
                window_samples(samples, since_ts=now - self.long_window * 60.0))

    def violation(
        self, domain: str, windows: tuple[list[Sample], list[Sample]], target: float,
    ) -> SloBurnViolation | None:
        """Compare both retained windows without changing equality or availability.

        Returns:
            The same result fields when both burn thresholds are met.
        """
        short_items, long_items = windows
        short_burn = compute_burn_rate(short_items, slo_target_percent=float(target))
        long_burn = compute_burn_rate(long_items, slo_target_percent=float(target))
        if short_burn is None or long_burn is None:
            return None
        if short_burn >= self.short_threshold and long_burn >= self.long_threshold:
            _, _, short_availability = compute_availability(short_items)
            _, _, long_availability = compute_availability(long_items)
            return SloBurnViolation(
                domain, self.name, self.short_window, self.long_window, float(short_burn), float(long_burn),
                float(short_availability) if short_availability is not None else None,
                float(long_availability) if long_availability is not None else None,
                len(short_items), len(long_items),
            )
        return None


def _coerce_rules(raw: JsonValue) -> list[JsonObject]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def compute_slo_burn_violations(
    *, history_by_domain: dict[str, list[Sample]], now_ts: float, slo_target_percent: float,
    burn_rate_rules: list[JsonValue], min_total_samples: int = 5,
) -> list[SloBurnViolation]:
    """Compare both burn windows to their original inclusive thresholds.

    Returns:
        Results sorted by domain/rule. Invalid sample minima remain loud.
    """
    rules = _coerce_rules(burn_rate_rules)
    violations: list[SloBurnViolation] = []
    now = float(now_ts)
    for domain, items in history_by_domain.items():
        if not items:
            continue
        for raw in rules:
            rule = BurnRule.parse(raw)
            if rule is None:
                continue
            short_items, long_items = rule.windows(items, now)
            if len(short_items) < required_int(raw.get("min_samples_short") or min_total_samples):
                continue
            if len(long_items) < required_int(raw.get("min_samples_long") or min_total_samples):
                continue
            violation = rule.violation(domain, (short_items, long_items), slo_target_percent)
            if violation is not None:
                violations.append(violation)
    violations.sort(key=attrgetter("domain", "rule"))
    return violations
