# Copyright (c) 2026 PitchAI. All rights reserved.
"""Configuration conversion preserves required and fallback semantics."""

from __future__ import annotations

import math
import unittest
from typing import TYPE_CHECKING

from .cycle_values import bool_field, coerce_float, coerce_int, coerce_optional_float, required_float, required_int
from .dft_test_support import require, require_error

if TYPE_CHECKING:
    from .event_bus_delivery import JsonValue


class TestCycleValues(unittest.TestCase):
    """Guard activation, numeric conversion, fallback and failure boundaries."""

    @staticmethod
    def test_numeric_scalars_retain_existing_conversion() -> None:
        """String, boolean and fractional input keep Python conversion rules."""
        values: list[tuple[JsonValue, int, float]] = [
            (True, 1, 1.0), (False, 0, 0.0), (" 12 ", 12, 12.0), (-2.75, -2, -2.75), (0, 0, 0.0),
        ]
        for value, integer, floating in values:
            require(condition=required_int(value) == integer and coerce_int(value) == integer,
                    message="integer conversion changed")
            require(condition=required_float(value) == floating and coerce_float(value) == floating,
                    message="float conversion changed")
        observed = coerce_optional_float("0.25")
        require(condition=observed is not None and math.isclose(observed, 0.25), message="optional threshold changed")
        require(condition=required_int(b"12") == int(b"12"), message="YAML binary integer changed")
        require(condition=math.isclose(required_float(b"2.5"), 2.5), message="YAML binary float changed")

    @staticmethod
    def test_invalid_required_values_fail_and_optional_values_fall_back() -> None:
        """Malformed values must not activate settings or fabricate limits."""
        values: list[JsonValue] = [None, [], [1], {}, {"value": 3}, "invalid", ""]
        integer_default, float_default = 17, 2.5
        for value in values:
            expected_error = ValueError if isinstance(value, str) else TypeError
            with require_error(expected_error, ""):
                _ = required_int(value)
            with require_error(expected_error, ""):
                _ = required_float(value)
            require(condition=coerce_int(value, default=integer_default) == integer_default,
                    message="integer default changed")
            require(condition=math.isclose(coerce_float(value, default=float_default), float_default),
                    message="float default changed")
            require(condition=coerce_optional_float(value) is None, message="invalid threshold invented")

    @staticmethod
    def test_nonfinite_values_preserve_existing_conversion_policy() -> None:
        """Extraction is not an unreviewed change to legacy numeric policy."""
        with require_error(OverflowError, "infinity"):
            _ = required_int(float("inf"))
        with require_error(ValueError, "NaN"):
            _ = required_int(float("nan"))
        fallback = 4
        require(condition=coerce_int(float("inf"), default=fallback) == fallback, message="overflow fallback changed")
        require(condition=math.isinf(coerce_float("inf")), message="float infinity policy changed")
        observed = coerce_optional_float("nan")
        require(condition=observed is not None and math.isnan(observed), message="optional NaN policy changed")

    @staticmethod
    def test_boolean_state_does_not_coerce_truthy_strings() -> None:
        """Only actual booleans override the supplied state default."""
        values: list[JsonValue] = ["false", "true", 0, 1, [], {"enabled": False}, None]
        for value in values:
            require(condition=bool_field({"last_ok": value}, "last_ok", default=True),
                    message="default true was coerced away")
            require(condition=not bool_field({"last_ok": value}, "last_ok", default=False),
                    message="invalid boolean activated state")
        require(condition=bool_field({"last_ok": True}, "last_ok", default=False), message="explicit true lost")
        require(condition=not bool_field({"last_ok": False}, "last_ok", default=True), message="explicit false lost")
