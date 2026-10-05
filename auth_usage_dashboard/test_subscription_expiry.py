# Copyright (c) 2026 PitchAI. All rights reserved.
"""Exact entitlement and local-calendar boundary proofs for subscription display."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, cast, final

from ._timeseries_test_fixtures import UsageTimeSeriesCase, check, check_equal
from .subscription_accounts import read_snapshot
from .subscription_accounts_check import validate_subscription_payload

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue


@final
class SubscriptionExpiryTest(UsageTimeSeriesCase):
    """Read only isolated fixtures, never reviewed production inventory."""

    def snapshot(self, row: JsonObject, *, now: str, zone: JsonValue = "Europe/Berlin") -> JsonObject:
        """Read a schema-1 candidate with controlled time and timezone.

        Returns:
            The public projection including evidence precision and freshness.
        """
        account: JsonObject = {
            "email": "expiry@example.test", "access_status": "active", "renewal_enabled": False,
            "access_ends_on": "2026-10-03", "verified_at": "2026-09-30T12:00:00Z",
            "verified_source": "signed-in billing evidence", **row,
        }
        document: JsonObject = {"schema_version": 1, "timezone": zone, "accounts": [account]}
        path = self.root / "expiry.json"
        _ = path.write_text(json.dumps(document), encoding="utf-8")
        return read_snapshot(path, now=datetime.fromisoformat(now).timestamp())

    def row(self, fields: JsonObject, *, now: str) -> JsonObject:
        """Return the single parsed fixture row.

        Returns:
            The account projected by the dashboard consumer.
        """
        snapshot = self.snapshot(fields, now=now)
        validate_subscription_payload(snapshot)
        return cast("list[JsonObject]", snapshot["accounts"])[0]

    def test_exact_before_equal_after_and_cancellation_are_distinct(self) -> None:
        """Only entitlement expiry flips access; earlier provider cancellation does not."""
        fields: JsonObject = {
            "access_ends_at": "2026-10-03T18:50:54Z",
            "provider_cancels_at": "2026-10-03T12:50:54Z",
            "cancellation_requested_at": "2026-09-09T07:12:41Z",
            "cancellation_scheduled": True,
        }
        cases = (
            ("2026-10-03T18:50:53.999999Z", "active_until_end"),
            ("2026-10-03T18:50:54Z", "access_ended"),
            ("2026-10-03T18:50:54.000001Z", "access_ended"),
        )
        for now, expected in cases:
            row = self.row(fields, now=now)
            check_equal(row["access_state"], expected, "exact boundary")
            check_equal(row["access_ends_at"], "2026-10-03T18:50:54+00:00", "exact value")
            check_equal(row["access_end_precision"], "exact", "precision")
            check_equal(row["cancellation_requested_at"], "2026-09-09T07:12:41+00:00", "request retained")
            check(row["cancellation_scheduled"] is True, "schedule flag retained")
            check("eligibility_cutoff_at" not in row, "invented eligibility cutoff")

    def test_date_only_remains_a_date_and_ends_at_local_midnight(self) -> None:
        """Berlin Oct4 begins at22UTC; date-only evidence never receives an exact value."""
        for now, expected in (
            ("2026-10-03T21:59:59Z", "active_until_end"),
            ("2026-10-03T22:00:00Z", "access_ended"),
        ):
            row = self.row({}, now=now)
            check_equal(row["access_state"], expected, "local end-day boundary")
            check_equal(row["access_ends_at"], None, "no promoted timestamp")
            check_equal(row["access_end_precision"], "date", "date precision")
        row = self.row({"access_ends_at": None}, now="2026-10-03T12:00:00Z")
        check_equal(row["access_end_precision"], "date", "null optional exact")
        row = self.row({"access_ends_on": None}, now="2026-10-03T12:00:00Z")
        check_equal(row["access_end_precision"], "unknown", "no invented end date")
        check_equal(row["access_state"], "unknown", "unknown expiry state")

    def test_dst_end_and_start_use_actual_local_calendar(self) -> None:
        """Local midnight follows the seasonal offset, not a fixed UTC offset."""
        for day, before, at in (
            ("2026-03-29", "2026-03-29T21:59:59Z", "2026-03-29T22:00:00Z"),
            ("2026-10-25", "2026-10-25T22:59:59Z", "2026-10-25T23:00:00Z"),
        ):
            fields: JsonObject = {"access_ends_on": day}
            check_equal(self.row(fields, now=before)["access_state"], "active_until_end", "DST before midnight")
            check_equal(self.row(fields, now=at)["access_state"], "access_ended", "DST midnight")
        for exact in ("2026-10-25T02:30:00+02:00", "2026-10-25T02:30:00+01:00"):
            fields = {"access_ends_on": "2026-10-25", "access_ends_at": exact}
            check_equal(self.row(fields, now=exact)["access_state"], "access_ended", "DST fold exact instant")

    def test_invalid_exact_evidence_never_falls_back_to_calendar(self) -> None:
        """Naive, malformed, or local-date-inconsistent instants stay visibly invalid."""
        invalid: tuple[JsonValue, ...] = (
            "2026-10-03T18:50:54", "2026-10-03", "garbage", "", True, 123, {},
            "2026-10-03T23:30:00Z", "2026-10-02T18:50:54Z",
        )
        for exact in invalid:
            row = self.row({"access_ends_at": exact}, now="2026-10-03T12:00:00Z")
            check_equal(row["access_state"], "unknown", "invalid evidence state")
            check_equal(row["access_end_precision"], "invalid", "invalid evidence precision")
            check_equal(row["access_ends_at"], None, "invalid timestamp suppressed")
        row = self.row({"access_ends_on": None, "access_ends_at": "2026-10-03T18:50:54Z"},
                       now="2026-10-03T12:00:00Z")
        check_equal(row["access_end_precision"], "invalid", "exact requires reviewed calendar date")
        row = self.row({"access_ends_at": "2026-10-02T22:30:00Z"}, now="2026-10-02T22:29:00Z")
        check_equal(row["access_end_precision"], "exact", "agreement uses local date not UTC date")
        row = self.row({"renewal_enabled": True, "access_ends_at": "invalid"}, now="2026-10-03T12:00:00Z")
        check_equal(row["access_state"], "unknown", "renewal cannot hide invalid exact evidence")

    def test_timezone_support_and_verification_metadata(self) -> None:
        """Supported declared zones control dates; unsupported zones cannot silently default."""
        for zone in ("UTC", "America/New_York", None):
            snapshot = self.snapshot({}, now="2026-10-03T22:00:00Z", zone=zone)
            rows = cast("list[JsonObject]", snapshot["accounts"])
            expected = "access_ended" if zone is None else "active_until_end"
            check_equal(rows[0]["access_state"], expected, "declared/default timezone")
        for zone in ("Not/AZone", "", 7):
            snapshot = self.snapshot({}, now="2026-10-03T22:00:00Z", zone=zone)
            check_equal(snapshot["accounts"], [], "unsupported timezone rows")
            check_equal(snapshot["error"], "Subscription timezone is unsupported", "explicit timezone error")
        row = self.row({"verified_at": "2026-11-01T12:00:00Z"}, now="2026-10-03T12:00:00Z")
        check(row["verified_stale"] is True, "future verification cannot look fresh")
        row = self.row({"verified_at": "2026-08-01T12:00:00Z"}, now="2026-10-03T12:00:00Z")
        check(row["verified_stale"] is True, "old verification flagged")
        check_equal(row["verified_source"], "signed-in billing evidence", "provenance preserved")
