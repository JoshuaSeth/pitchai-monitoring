from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain_checks.main import _normalize_domain_entries, _parse_disabled_until_ts


def test_parse_disabled_until_ts_accepts_unix_timestamp() -> None:
    assert _parse_disabled_until_ts(123) == 123.0
    assert _parse_disabled_until_ts("123.5") == 123.5


def test_parse_disabled_until_ts_accepts_iso_datetime_z() -> None:
    ts = _parse_disabled_until_ts("2099-01-01T00:00:00Z")
    assert ts == datetime(2099, 1, 1, tzinfo=timezone.utc).timestamp()


def test_parse_disabled_until_ts_invalid_raises() -> None:
    with pytest.raises(ValueError):
        _parse_disabled_until_ts("not-a-timestamp")


def test_normalize_domain_entries_handles_disabled_flags() -> None:
    entries = _normalize_domain_entries(
        [
            {"domain": "a", "disabled": True},
            {"domain": "b", "enabled": False},
            {"domain": "c", "disabled_until": 2000},
            {"domain": "d", "disabled_until": 500},
        ]
    )

    by_domain = {e.domain: e for e in entries}
    now_ts = 1000.0

    assert by_domain["a"].is_disabled(now_ts) is True
    assert by_domain["b"].is_disabled(now_ts) is True
    assert by_domain["c"].is_disabled(now_ts) is True
    assert by_domain["d"].is_disabled(now_ts) is False


def test_dispatch_domain_is_forced_disabled() -> None:
    entries = _normalize_domain_entries(["dispatch.pitchai.net"])
    assert len(entries) == 1
    assert entries[0].domain == "dispatch.pitchai.net"
    assert entries[0].disabled is True
    assert entries[0].disabled_reason
