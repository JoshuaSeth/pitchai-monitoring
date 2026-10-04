# Copyright (c) 2026 PitchAI. All rights reserved.
"""Compatibility tests for the shared disabled-until parser."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import cast

from domain_checks.dft_test_support import require, require_error
from e2e_registry.disablement import parse_disabled_until


def test_empty_and_nonpositive_values_remain_unset() -> None:
    """Empty and nonpositive values retain the unset result."""
    for value in (None, "", "  ", 0, -1, "0", "-1"):
        require(condition=parse_disabled_until(value) is None, message=f"value remained active: {value!r}")


def test_numeric_and_iso_values_keep_original_precedence() -> None:
    """Numeric, date and UTC datetime inputs retain their original values."""
    expected_integer = 123.0
    expected_numeric_string = 123.5
    require(condition=math.isclose(cast("float", parse_disabled_until(123)), expected_integer),
            message="integer parsing changed")
    require(condition=math.isclose(cast("float", parse_disabled_until("123.5")), expected_numeric_string),
            message="numeric string parsing changed")
    expected = datetime(2099, 1, 1, tzinfo=UTC).timestamp()
    require(condition=math.isclose(cast("float", parse_disabled_until("2099-01-01")), expected),
            message="date parsing changed")
    require(condition=math.isclose(cast("float", parse_disabled_until("2099-01-01T00:00:00Z")), expected),
            message="UTC datetime parsing changed")


def test_invalid_iso_value_preserves_historical_error_text() -> None:
    """Malformed values retain the API's historical ValueError text."""
    with require_error(ValueError, "Invalid isoformat string: 'not-a-timestamp'"):
        parse_disabled_until("not-a-timestamp")
