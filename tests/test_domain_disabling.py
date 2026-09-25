# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tests for test domain disabling behavior."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from domain_checks.main import normalize_domain_entries, parse_disabled_until_ts
from domain_checks.testing import verify

_UNIX_TIMESTAMP = 123.0
_FRACTIONAL_UNIX_TIMESTAMP = 123.5


def test_parse_disabled_until_ts_accepts_unix_timestamp() -> None:
    """Verify parse disabled until ts accepts unix timestamp."""
    integer_timestamp = parse_disabled_until_ts(123)
    fractional_timestamp = parse_disabled_until_ts("123.5")
    verify(integer_timestamp is not None and math.isclose(integer_timestamp, _UNIX_TIMESTAMP))
    verify(
        fractional_timestamp is not None and math.isclose(fractional_timestamp, _FRACTIONAL_UNIX_TIMESTAMP),
    )


def test_parse_disabled_until_ts_accepts_iso_datetime_z() -> None:
    """Verify parse disabled until ts accepts iso datetime z."""
    ts = parse_disabled_until_ts("2099-01-01T00:00:00Z")
    verify(ts == datetime(2099, 1, 1, tzinfo=UTC).timestamp())


def test_parse_disabled_until_ts_invalid_raises() -> None:
    """Verify parse disabled until ts invalid raises."""
    with pytest.raises(ValueError, match="Invalid disabled_until value"):
        _ = parse_disabled_until_ts("not-a-timestamp")


def test_normalize_domain_entries_handles_disabled_flags() -> None:
    """Verify normalize domain entries handles disabled flags."""
    entries = normalize_domain_entries(
        [
            {"domain": "a", "disabled": True},
            {"domain": "b", "enabled": False},
            {"domain": "c", "disabled_until": 2000},
            {"domain": "d", "disabled_until": 500},
        ],
    )

    by_domain = {e.domain: e for e in entries}
    now_ts = 1000.0

    verify(by_domain["a"].is_disabled(now_ts) is True)
    verify(by_domain["b"].is_disabled(now_ts) is True)
    verify(by_domain["c"].is_disabled(now_ts) is True)
    verify(by_domain["d"].is_disabled(now_ts) is False)


def test_remote_domain_is_not_silently_disabled() -> None:
    """Verify remote domain is not silently disabled."""
    entries = normalize_domain_entries(["dispatch.pitchai.net"])
    verify(len(entries) == 1)
    verify(entries[0].domain == "dispatch.pitchai.net")
    verify(entries[0].disabled is False)
    verify(entries[0].disabled_reason is None)
