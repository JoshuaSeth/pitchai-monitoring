# Copyright (c) 2026 PitchAI. All rights reserved.
"""Independent scalar health counters shared by the cycle's metric families."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from .alert_transition import update_effective_ok
from .cycle_values import bool_field, coerce_int

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .alert_settings import AlertSettings
    from .event_bus_delivery import JsonObject, JsonValue


@dataclass
class HealthState:
    """Own one monitor's effective health and consecutive observation counts."""

    last_ok: bool = True
    fail_streak: int = 0
    success_streak: int = 0

    @classmethod
    def from_section(cls, section: Mapping[str, JsonValue]) -> Self:
        """Resume the three counters without taking ownership of extra fields.

        Returns:
            Existing boolean/integer normalization with independent defaults.
        """
        return cls(
            last_ok=bool_field(section, "last_ok", default=True),
            fail_streak=coerce_int(section.get("fail_streak"), default=0),
            success_streak=coerce_int(section.get("success_streak"), default=0),
        )

    def advance(self, *, observed_ok: bool, thresholds: AlertSettings) -> bool:
        """Apply one observation with the same configured debounce thresholds.

        Returns:
            Whether this observation crossed from effective UP to DOWN.
            A healthy observation cannot skip the required recovery streak.
        """
        self.last_ok, self.fail_streak, self.success_streak, alerted_down = update_effective_ok(
            prev_effective_ok=bool(self.last_ok),
            observed_ok=observed_ok,
            fail_streak=int(self.fail_streak),
            success_streak=int(self.success_streak),
            down_after_failures=thresholds.down_after_failures,
            up_after_successes=thresholds.up_after_successes,
        )
        return alerted_down

    def to_state(self) -> JsonObject:
        """Build the unchanged persisted trio without exposing mutable aliases.

        Returns:
            A fresh mapping for the original schema-six section.
        """
        return {"last_ok": bool(self.last_ok), "fail_streak": int(self.fail_streak),
                "success_streak": int(self.success_streak)}
