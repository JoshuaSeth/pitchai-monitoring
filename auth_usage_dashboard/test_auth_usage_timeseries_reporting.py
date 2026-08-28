# Copyright (c) 2026 PitchAI. All rights reserved.
"""Legacy migration and reporting proof for durable usage history."""

from __future__ import annotations

import json
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import TYPE_CHECKING, cast, final

from ._timeseries_test_fixtures import (
    NOW,
    AccountOverrides,
    UsageTimeSeriesCase,
    check,
    check_equal,
    legacy_payload,
    parsed_account,
    raw_account,
    require_array,
)
from .history_cli import main as history_main
from .timeseries_reporting import recent_rows, window_summary
from .timeseries_types import require_object

if TYPE_CHECKING:
    from .timeseries_store import UsageTimeSeriesStore
    from .timeseries_types import JsonValue

EXPECTED_HISTORY_SAMPLES = 3


@final
class UsageTimeSeriesReportingTest(UsageTimeSeriesCase):
    """Exercise legacy import and bounded operator reports."""

    def test_legacy_json_is_transactionally_imported_once(self) -> None:
        """Migrate the legacy JSON ledger once and retain its account identity."""
        legacy = self.root / "usage-samples.json"
        legacy.write_text(json.dumps(legacy_payload()), encoding="utf-8")
        store = self.store(legacy=legacy)
        raw = [raw_account("Seth", "internal-seth")]
        check(
            store.record([parsed_account("Seth")], raw_accounts=raw, at=NOW),
            "current batch was not recorded",
        )
        changed = AccountOverrides(used=30.0, remaining=70.0)
        check(
            store.record(
                [parsed_account("Seth", changed)],
                raw_accounts=raw,
                at=NOW + timedelta(minutes=5),
            ),
            "second current batch was not recorded",
        )

        rows = recent_rows(store.path, account_label="Seth", limit=10)
        check_equal(len(rows), EXPECTED_HISTORY_SAMPLES, "migrated row count")
        check_equal(rows[-1]["source"], "auth_usage_dashboard:legacy_json_v1", "legacy source")
        references: set[str] = set()
        for row in rows:
            account_ref = row.get("account_ref")
            if not isinstance(account_ref, str):
                self.fail("history row account reference must be text")
            references.add(account_ref)
        check_equal(len(references), 1, "account reference count")

    def test_last_24_hour_summary(self) -> None:
        """Expose bounded per-account counts for the last day."""
        store = self._populated_store()
        summary = window_summary(store.path, hours=24, now=datetime.now(UTC))
        account_values = require_array(summary.get("accounts"), "summary accounts")
        accounts = [require_object(account_value, description="summary account") for account_value in account_values]
        check_equal(summary["account_count"], 2, "summary account count")
        sample_counts = [account.get("sample_count") for account in accounts]
        check_equal(
            sample_counts,
            [EXPECTED_HISTORY_SAMPLES, EXPECTED_HISTORY_SAMPLES],
            "per-account sample counts",
        )

    def test_cli_output(self) -> None:
        """Emit valid bounded summary and auth-invalid recent JSON."""
        store = self._populated_store()
        summary_output = StringIO()
        with redirect_stdout(summary_output):
            summary_status = history_main(["--database", str(store.path), "summary", "--hours", "24"])
        summary_decoded = cast("JsonValue", json.loads(summary_output.getvalue()))
        summary_payload = require_object(summary_decoded, description="summary output")
        check_equal(summary_status, 0, "summary CLI exit status")
        check_equal(summary_payload["batch_count"], EXPECTED_HISTORY_SAMPLES, "summary batch count")

        recent_output = StringIO()
        with redirect_stdout(recent_output):
            recent_status = history_main(
                ["--database", str(store.path), "recent", "--account", "Info", "--limit", "2"],
            )
        recent_decoded = cast("JsonValue", json.loads(recent_output.getvalue()))
        recent_payload = require_array(recent_decoded, "recent output")
        check_equal(recent_status, 0, "recent CLI exit status")
        check_equal(len(recent_payload), 2, "recent output row count")
        auth_states: list[JsonValue] = []
        for row_value in recent_payload:
            row = require_object(row_value, description="recent row")
            auth_states.append(row.get("auth_state"))
        check_equal(auth_states, ["invalid", "invalid"], "recent auth states")

    def _populated_store(self) -> UsageTimeSeriesStore:
        store = self.store()
        raw = [raw_account("Seth", "internal-seth"), raw_account("Info", "internal-info")]
        invalid = AccountOverrides(auth_valid=False, status="auth_invalid")
        base = datetime.now(UTC) - timedelta(minutes=10)
        for offset in range(EXPECTED_HISTORY_SAMPLES):
            check(
                store.record(
                    [parsed_account("Seth"), parsed_account("Info", invalid)],
                    raw_accounts=raw,
                    at=base + timedelta(minutes=offset * 5),
                ),
                "history batch was not recorded",
            )
        return store
