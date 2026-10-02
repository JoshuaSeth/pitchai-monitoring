# Copyright (c) 2026 PitchAI. All rights reserved.
"""Preserve optional-section values and aliasing during cycle extraction."""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from .cycle_configuration import cycle_section
from .dft_test_support import require

if TYPE_CHECKING:
    from .event_bus_delivery import JsonValue


class TestCycleConfiguration(unittest.TestCase):
    """Configuration lookup never changes activation or invents defaults."""

    @staticmethod
    def test_populated_mapping_preserves_values_and_identity() -> None:
        """Explicit disabled state, custom limits and nested values survive."""
        proxy: dict[str, JsonValue] = {"enabled": False, "window_seconds": 300, "custom": {"limit": 0}}
        config: dict[str, JsonValue] = {"proxy": proxy, "history": {"retention_seconds": 123}}
        observed = cycle_section(config, "proxy")
        require(condition=observed is proxy and observed["enabled"] is False,
                message="section lookup copied or activated the configured mapping")
        require(condition=cycle_section(config, "history") == {"retention_seconds": 123},
                message="section lookup replaced caller-supplied values")

    @staticmethod
    def test_missing_empty_and_non_mapping_values_stay_unconfigured() -> None:
        """Fallback dictionaries are isolated, including empty configured maps."""
        values: list[JsonValue] = [None, False, True, 0, 1, "", "enabled", [], ["enabled"], {}]
        for value in values:
            config: dict[str, JsonValue] = {"proxy": value}
            observed = cycle_section(config, "proxy")
            require(condition=not observed, message="invalid optional section became configured")
            observed["enabled"] = True
            require(condition=not cycle_section(config, "proxy"),
                    message="fallback mutation changed the source configuration")
        require(condition=not cycle_section({}, "heartbeat"), message="missing section acquired defaults")
