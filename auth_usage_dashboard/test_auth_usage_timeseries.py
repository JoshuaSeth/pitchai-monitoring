# Copyright (c) 2026 PitchAI. All rights reserved.
"""Schema, append-only, and auth-invalid usage-history proof."""

from __future__ import annotations

import json
import secrets
import sqlite3
import stat
from datetime import timedelta
from typing import TYPE_CHECKING, cast, final

from ._timeseries_test_fixtures import (
    NOW,
    AccountOverrides,
    UsageTimeSeriesCase,
    check,
    check_close,
    check_equal,
    parsed_account,
    raw_account,
    require_array,
)
from .timeseries_reporting import database_status, recent_rows
from .timeseries_rows import sanitized_error_code

if TYPE_CHECKING:
    from .timeseries_store import UsageTimeSeriesStore
    from .timeseries_types import JsonValue

EXPECTED_BATCH_COUNT = 2
EXPECTED_SAMPLE_COUNT = 4


@final
class UsageTimeSeriesTest(UsageTimeSeriesCase):
    """Exercise schema, append behavior, and invalid-auth carry-forward."""

    def test_schema_creation_and_append_only_all_account_sampling(self) -> None:
        """Create the schema and retain distinct complete account batches."""
        store = self.store()
        raw = [raw_account("Seth", "internal-seth"), raw_account("Info", "internal-info")]
        invalid = AccountOverrides(auth_valid=False, status="auth_invalid")
        accounts = [parsed_account("Seth"), parsed_account("Info", invalid)]
        secret_value = secrets.token_hex(16)
        accounts[0]["access_token"] = secret_value

        check(store.record(accounts, raw_accounts=raw, at=NOW), "initial batch was not recorded")
        check(
            not store.record(accounts, raw_accounts=raw, at=NOW + timedelta(minutes=1)),
            "cadence gate admitted an early batch",
        )
        changed = AccountOverrides(used=30.0, remaining=70.0)
        check(
            store.record(
                [parsed_account("Seth", changed), accounts[1]],
                raw_accounts=raw,
                at=NOW + timedelta(minutes=5),
            ),
            "due batch was not recorded",
        )

        _verify_store(store, secret_value)

    def test_auth_invalid_sample_keeps_explicit_last_known_fields(self) -> None:
        """Carry prior values for invalid auth while labeling them last-known."""
        store = self.store()
        raw = [raw_account("Info", "internal-info"), raw_account("Support", "internal-support")]
        check(
            store.record(
                [parsed_account("Info"), parsed_account("Support")],
                raw_accounts=raw,
                at=NOW,
            ),
            "baseline batch was not recorded",
        )
        invalid_values = AccountOverrides(
            auth_valid=False,
            status="auth_invalid",
            used=None,
            remaining=None,
            redeemable_count=None,
            stale=True,
            probe_error="auth_invalid",
        )
        support_values = AccountOverrides(used=40.0, remaining=60.0)
        check(
            store.record(
                [parsed_account("Info", invalid_values), parsed_account("Support", support_values)],
                raw_accounts=raw,
                at=NOW + timedelta(minutes=5),
            ),
            "auth-invalid batch was not recorded",
        )

        latest = recent_rows(store.path, account_label="Info", limit=1)[0]
        check_equal(latest["auth_state"], "invalid", "auth state")
        check_equal(latest["values_source"], "last_known", "values source")
        check_close(latest["five_used_percent"], 25.0, "five-hour usage")
        check_close(latest["five_remaining_percent"], 75.0, "five-hour remaining")
        check_equal(latest["redeemable_count"], 2, "redeemable count")
        check_equal(latest["provider_stale"], 1, "provider stale flag")
        check_equal(latest["probe_error"], "auth_invalid", "probe error")
        decoded = cast("JsonValue", json.loads(str(latest["carried_fields_json"])))
        carried = require_array(decoded, "carried fields")
        check("five_used_percent" in carried, "usage field was not carried")
        support_rows = recent_rows(store.path, account_label="Support", limit=10)
        check_equal(len(support_rows), 2, "support sample count")

    def test_new_collector_version_records_immediate_complete_batch(self) -> None:
        """Record deployment proof without waiting out the prior version's cadence."""
        store = self.store()
        raw = [raw_account("Seth", "internal-seth")]
        accounts = [parsed_account("Seth")]
        check(store.record(accounts, raw_accounts=raw, at=NOW), "baseline batch was not recorded")
        replacement = type(store)(
            store.path,
            sample_interval_seconds=store.sample_interval_seconds,
            collector_version="replacement-sha",
        )
        check(
            replacement.record(accounts, raw_accounts=raw, at=NOW + timedelta(minutes=1)),
            "replacement version did not record an immediate batch",
        )
        status_payload = database_status(store.path)
        check_equal(status_payload["latest_collector_version"], "replacement-sha", "latest collector version")
        check_equal(status_payload["latest_batch_account_count"], 1, "latest account count")
        check_equal(status_payload["latest_batch_sample_count"], 1, "latest sample count")

    @staticmethod
    def test_free_form_provider_error_is_fingerprinted() -> None:
        """Keep an actionable error identity without retaining free-form secrets."""
        error = "provider rejected Bearer secret-material"
        sanitized = sanitized_error_code(error) or ""
        check(bool(sanitized), "sanitized error was not retained")
        check(sanitized.startswith("error-sha256:"), "free-form error was not fingerprinted")
        check("secret-material" not in sanitized, "free-form error leaked into its fingerprint")


def _verify_store(store: UsageTimeSeriesStore, secret_value: str) -> None:
    status_payload = database_status(store.path)
    check_equal(status_payload["schema_version"], 1, "schema version")
    check_equal(status_payload["batch_count"], EXPECTED_BATCH_COUNT, "batch count")
    check_equal(status_payload["sample_count"], EXPECTED_SAMPLE_COUNT, "sample count")
    check_equal(status_payload["latest_batch_account_count"], 2, "latest account count")
    check_equal(status_payload["latest_batch_sample_count"], 2, "latest sample count")
    with sqlite3.connect(store.path) as connection:
        usage_rows = cast(
            "list[tuple[float]]",
            connection.execute(
                """SELECT five_used_percent FROM account_usage_samples
                   WHERE account_label = 'Seth' ORDER BY sample_id""",
            ).fetchall(),
        )
        column_rows = cast(
            "list[tuple[int, str, str, int, JsonValue, int]]",
            connection.execute("PRAGMA table_info(account_usage_samples)").fetchall(),
        )
    columns = {row[1] for row in column_rows}
    check_equal(usage_rows, [(25.0,), (30.0,)], "retained usage rows")
    required_columns = {"account_ref", "auth_state", "redeemable_count", "collector_version"}
    check(required_columns <= columns, "required schema columns are missing")
    check_equal(stat.S_IMODE(store.path.parent.stat().st_mode), 0o700, "directory mode")
    check_equal(stat.S_IMODE(store.path.stat().st_mode), 0o600, "database mode")
    history_paths = store.path.parent.glob("usage-history.sqlite3*")
    retained_parts = [path.read_bytes() for path in history_paths]
    retained = b"".join(retained_parts)
    check(secret_value.encode() not in retained, "secret escaped into SQLite")
    check(b"internal-seth" not in retained, "raw account identifier escaped into SQLite")
