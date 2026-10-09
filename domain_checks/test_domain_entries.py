# Copyright (c) 2026 PitchAI. All rights reserved.
"""Synthetic inventory expiry and normalization compatibility cases."""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from math import isclose
from typing import TYPE_CHECKING

from .dft_test_support import require, require_error
from .domain_entries import format_disabled_domain_line, normalize_domain_entries
from .domain_time import load_timezone, parse_disabled_until_ts, parse_hhmm

if TYPE_CHECKING:
    from .config_values import ConfigValue


class DomainEntryTests(unittest.TestCase):
    """Preserve existing local input and explicit-stop semantics."""

    @staticmethod
    def test_calendar_and_numeric_expiry_rules_are_distinct() -> None:
        """Calendar pre-epoch values stay absolute; nonpositive numbers are absent."""
        for value in (0, -1, "0", "-1", "NaN", None):
            require(condition=parse_disabled_until_ts(value) is None, message="nonpositive numeric expiry changed")
        expected = datetime(1969, 12, 31, tzinfo=UTC).timestamp()
        require(condition=parse_disabled_until_ts("1969-12-31") == expected, message="calendar timestamp discarded")
        require(condition=parse_disabled_until_ts(date(1969, 12, 31)) == expected, message="YAML date input changed")
        expected_boolean = 1.0
        require(condition=parse_disabled_until_ts(value=True) == expected_boolean, message="boolean conversion changed")

    @staticmethod
    def test_offsets_and_expiry_equality() -> None:
        """Repeated DST hours retain their supplied offsets and equality expires."""
        early = parse_disabled_until_ts("2026-10-25T02:30:00+02:00")
        late = parse_disabled_until_ts("2026-10-25T02:30:00+01:00")
        require(condition=early is not None and late is not None, message="offset timestamp missing")
        expected_offset = 3600.0
        difference = float(late or 0) - float(early or 0)
        require(condition=isclose(difference, expected_offset, rel_tol=0, abs_tol=0), message="DST offset collapsed")
        entry = normalize_domain_entries([{"domain": "fixture.invalid", "disabled_until": 100}])[0]
        require(condition=entry.is_disabled(99) and not entry.is_disabled(100), message="expiry equality changed")
        stopped = normalize_domain_entries([{"domain": "fixture.invalid", "disabled": True, "disabled_until": 100}])[0]
        require(condition=stopped.is_disabled(101), message="explicit stop expired")

    @staticmethod
    def test_normalization_preserves_raw_mapping_and_policy() -> None:
        """Normalized identity must not rewrite the caller's retained configuration."""
        raw: dict[str, ConfigValue] = {
            "domain": " fixture.invalid ", "disabled_reason": " planned ", "enabled": False,
            "alert_policy": {"telegram": "dashboard-only", "reason": "fixture"},
        }
        entry = normalize_domain_entries([raw])[0]
        require(condition=entry.raw_entry is raw and raw["domain"] == " fixture.invalid ",
                message="raw mapping rewritten")
        require(condition=entry.domain == "fixture.invalid" and not entry.routes_telegram, message="policy changed")
        require(condition=entry.is_disabled(0) and entry.disabled_reason == "planned", message="stop fields changed")
        require(
            condition=format_disabled_domain_line(entry, UTC) == "- fixture.invalid: DISABLED (planned)",
            message="disabled display changed",
        )

    @staticmethod
    def test_invalid_and_duplicate_entries_still_fail() -> None:
        """Invalid shape, policy and duplicate identities cannot silently disappear."""
        with require_error(ValueError, "Duplicate domain entry"):
            normalize_domain_entries(["fixture.invalid", {"domain": "fixture.invalid"}])
        with require_error(ValueError, "must be a string or mapping"):
            normalize_domain_entries([None])
        with require_error(ValueError, "reason is required"):
            normalize_domain_entries([{"domain": "fixture.invalid", "alert_policy": {"telegram": "dashboard-only"}}])
        with require_error(ValueError, "Invalid disabled_until"):
            parse_disabled_until_ts("not-a-date")

    @staticmethod
    def test_time_boundaries_and_timezone_fallback() -> None:
        """Preserve flexible numeric fields, invalid-field refusal and UTC fallback."""
        require(condition=parse_hhmm(" 1:02 ").isoformat() == "01:02:00", message="hour/minute whitespace changed")
        with require_error(ValueError, "Invalid time"):
            parse_hhmm("24:00")
        with require_error(ValueError, "invalid literal"):
            parse_hhmm("12:00:00")
        require(condition=load_timezone("utc") is UTC, message="UTC changed")
        require(condition=load_timezone("Synthetic/Missing") is UTC, message="unknown zone fallback changed")
