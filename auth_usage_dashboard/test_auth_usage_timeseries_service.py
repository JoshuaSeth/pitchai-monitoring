# Copyright (c) 2026 PitchAI. All rights reserved.
"""Integration proof for the file-only periodic usage-history collector."""

from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, final

from ._timeseries_test_fixtures import check, check_close, check_equal, isolated_root
from .timeseries_collector import CollectorConfiguration, UsageHistoryCollector
from .timeseries_reporting import database_status, recent_rows
from .timeseries_store import UsageTimeSeriesStore

if TYPE_CHECKING:
    from pathlib import Path

    from .timeseries_types import JsonObject

SAMPLE_INTERVAL_SECONDS = 300
NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class InventoryAccount:
    """One redacted broker account fixture."""

    directory: str
    label: str
    account_id: str
    auth_invalid: bool
    state_missing: bool = False


@final
class UsageHistoryCollectorTest(unittest.TestCase):
    """Prove collection reads the full inventory without provider calls."""

    root: Path
    accounts: Path

    def setUp(self) -> None:
        """Create an isolated broker inventory and durable store path."""
        self.root = self.enterContext(isolated_root())
        self.accounts = self.root / "broker" / "accounts"
        self.accounts.mkdir(parents=True)

    def test_collect_once_reads_every_account_and_records_invalid_auth(self) -> None:
        """Record valid and invalid accounts without mutating broker snapshots."""
        self._write_account(InventoryAccount("seth", "Seth", "internal-seth", auth_invalid=False))
        self._write_account(InventoryAccount("info", "Info", "internal-info", auth_invalid=True))
        self._write_account(
            InventoryAccount("support", "Support", "internal-support", auth_invalid=False, state_missing=True),
        )
        before = self._inventory_digest()
        database = self.root / "persistent" / "usage-history.sqlite3"
        store = UsageTimeSeriesStore(
            database,
            sample_interval_seconds=SAMPLE_INTERVAL_SECONDS,
            collector_version="integration-sha",
        )
        configuration = CollectorConfiguration(
            broker_data_dir=self.root / "broker",
            stale_after_seconds=600,
            analytics_stale_after_seconds=1_800,
            min_five_hour_remaining_percent=5.0,
            interval_seconds=SAMPLE_INTERVAL_SECONDS,
            startup_delay_seconds=0,
        )
        collector = UsageHistoryCollector(configuration, store)
        self.addCleanup(collector.stop)

        check(collector.collect_once(at=NOW), "collector did not record its first batch")
        check_equal(self._inventory_digest(), before, "broker inventory digest")
        check_equal(database_status(database)["sample_count"], 3, "sample count")
        seth = recent_rows(database, account_label="Seth", limit=1)[0]
        info = recent_rows(database, account_label="Info", limit=1)[0]
        support = recent_rows(database, account_label="Support", limit=1)[0]
        check_equal(seth["auth_state"], "valid", "Seth auth state")
        check_equal(seth["collector_version"], "integration-sha", "collector version")
        check_close(seth["five_remaining_percent"], 75.0, "Seth remaining usage")
        check_equal(info["auth_state"], "invalid", "Info auth state")
        check_equal(info["values_source"], "unavailable", "Info values source")
        check_equal(info["probe_error"], "refresh_failed", "Info probe error")
        check_equal(support["auth_state"], "unknown", "Support auth state")
        check_equal(support["probe_error"], "state_file_missing", "Support probe error")

    def _write_account(self, account: InventoryAccount) -> None:
        root = self.accounts / account.directory
        root.mkdir()
        metadata: JsonObject = {
            "label": account.label,
            "account_id": account.account_id,
            "enabled": True,
        }
        (root / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        if account.state_missing:
            return
        state: JsonObject = {
            "availability": "auth_invalid" if account.auth_invalid else "available",
            "last_probe_at": NOW.isoformat(),
            "last_error": "refresh_failed" if account.auth_invalid else None,
        }
        if not account.auth_invalid:
            state["usage"] = _usage(account.label)
        (root / "state.json").write_text(json.dumps(state), encoding="utf-8")

    def _inventory_digest(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(self.accounts.glob("*/*.json")):
            digest.update(path.relative_to(self.accounts).as_posix().encode())
            digest.update(path.read_bytes())
        return digest.hexdigest()


def _usage(label: str) -> JsonObject:
    return {
        "email": label,
        "rate_limit": {
            "primary_window": {
                "used_percent": 25,
                "reset_at": (NOW + timedelta(hours=3)).isoformat(),
                "limit_window_seconds": 18_000,
            },
            "secondary_window": {
                "used_percent": 10,
                "reset_at": (NOW + timedelta(days=5)).isoformat(),
                "limit_window_seconds": 604_800,
            },
        },
        "rate_limit_reset_credits": {"available_count": 2},
    }
