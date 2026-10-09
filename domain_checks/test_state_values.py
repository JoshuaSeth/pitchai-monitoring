# Copyright (c) 2026 PitchAI. All rights reserved.
"""Retained-state decoding must not fabricate counters or collapse events."""

from __future__ import annotations

import math
import unittest
from typing import TYPE_CHECKING

from .dft_test_support import require
from .state_values import (
    coerce_bool_dict,
    coerce_float_dict,
    coerce_int_dict,
    coerce_list_of_dicts,
    coerce_signal_history,
    coerce_str_list_dict,
)

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject, JsonValue


class TestStateValues(unittest.TestCase):
    """Verify malformed input, stable order, bounded rows and independent maps."""

    @staticmethod
    def test_counters_omit_bad_values_without_resetting_other_domains() -> None:
        """A bad counter cannot erase a healthy domain's retained streak."""
        raw: JsonObject = {"first": "2", "second": 3.75, "bad": "invalid", "null": None, "nested": [3], "yes": True}
        require(condition=coerce_int_dict(raw) == {"first": 2, "second": 3, "yes": 1},
                message="counter conversion or omission changed")
        require(condition=coerce_bool_dict(raw) == {"yes": True}, message="truthy nonboolean became effective health")
        floating = coerce_float_dict({"nan": "nan", "inf": "inf", "bad": [], "valid": "2.5"})
        require(condition=math.isnan(floating["nan"]) and math.isinf(floating["inf"]),
                message="legacy nonfinite timestamp policy changed")
        require(condition="bad" not in floating and math.isclose(floating["valid"], 2.5),
                message="timestamp conversion fabricated a value")
        require(condition=not coerce_int_dict({"infinity": float("inf"), "nan": float("nan")}),
                message="nonconvertible integer was retained")

    @staticmethod
    def test_address_lists_preserve_order_duplicates_and_empty_lists() -> None:
        """Address comparison must use the same normalized values after restart."""
        raw: JsonObject = {"first": [" a ", "a", 0, None, "", 7], "empty": [], "bad": "a"}
        require(condition=coerce_str_list_dict(raw) == {"first": ["a", "a", "7"], "empty": []},
                message="address list normalization changed")

    @staticmethod
    def test_retained_objects_keep_duplicate_identity_and_prefix_limits() -> None:
        """History limits retain earliest objects, without content deduplication."""
        first: JsonObject = {"kind": "synthetic", "ordinal": 1}
        second: JsonObject = dict(first)
        raw: list[JsonValue] = [None, "bad", first, [], second, {"ordinal": 2}]
        limit = 2
        observed = coerce_list_of_dicts(raw, max_items=limit)
        require(condition=len(observed) == limit and observed[0] is first and observed[1] is second,
                message="history identity or order changed")
        require(condition=coerce_list_of_dicts(raw, max_items=0) == [first], message="legacy minimum limit changed")

    @staticmethod
    def test_signal_rows_wait_for_valid_lists_and_keep_original_prefix() -> None:
        """Empty or scalar samples are omitted, and normalized-key behavior stays."""
        first: list[JsonValue] = [1, False]
        second: list[JsonValue] = [1, False]
        raw: JsonObject = {" signal ": [[], None, first, "bad", second, [2, True]], "empty": [], " ": [[1]]}
        observed = coerce_signal_history(raw, max_samples_per_signal=2)
        require(condition=list(observed) == ["signal"] and observed["signal"] == [first, second],
                message="signal filtering or prefix limit changed")
        require(condition=observed["signal"][0] is first and observed["signal"][1] is second,
                message="signal rows copied or collapsed")
        require(condition=coerce_signal_history(raw, max_samples_per_signal=-1) == {"signal": [first]},
                message="signal minimum limit changed")

    @staticmethod
    def test_wrong_container_shapes_produce_empty_collections() -> None:
        """Scalar state cannot become a domain counter, event or signal."""
        for raw in (None, True, "bad", 3):
            require(condition=not coerce_bool_dict(raw) and not coerce_int_dict(raw),
                    message="invalid mapping accepted")
            require(condition=not coerce_float_dict(raw) and not coerce_str_list_dict(raw),
                    message="invalid value map accepted")
            require(condition=not coerce_signal_history(raw) and not coerce_list_of_dicts(raw),
                    message="invalid history accepted")
