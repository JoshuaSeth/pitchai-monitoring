# Copyright (c) 2026 PitchAI. All rights reserved.
"""Unit and endpoint proof for the verified-subscription snapshot boundary."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, cast, final
from unittest.mock import patch

from ._scheduling_capacity_test_fixtures import (
    StaticCapacityService,
    dashboard_settings,
    operator_snapshot,
)
from ._timeseries_test_fixtures import UsageTimeSeriesCase, check, check_equal
from .scheduling_app import create_scheduling_app
from .scheduling_web_runtime import test_client_factory
from .subscription_accounts import MAX_SNAPSHOT_BYTES, read_snapshot
from .subscription_routes import SUBSCRIPTION_ACCOUNTS_FILE_ENVIRONMENT_VARIABLE

if TYPE_CHECKING:
    from pathlib import Path

    from .scheduling_web_runtime import Application
    from .service import CapacityService, StateSource
    from .timeseries_types import JsonObject

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC).timestamp()
UNAVAILABLE = "Subscription status is unavailable"
OPERATOR_HEADERS = {"X-PitchAI-Email": "priority-engine@pitchai.net"}
FOREIGN_HEADERS = {"X-PitchAI-Email": "operator@example.com"}


def subscription_document() -> JsonObject:
    """Return one curated snapshot covering every derived access state."""
    return {
        "schema_version": 1,
        "generated_at": "2026-09-28T13:05:00+02:00",
        "timezone": "Europe/Berlin",
        "accounts": [
            {
                "email": "info@pitchai.net",
                "protected": True,
                "plan": "ChatGPT Pro 20x",
                "access_status": "active",
                "renewal_enabled": True,
                "cancellation_scheduled": False,
                "renews_on": "2026-10-16",
                "verified_at": "2026-09-17T13:24:00+02:00",
                "verified_source": "chatgpt.com Billing page (signed-in)",
            },
            {
                "email": "support@pitchai.net",
                "plan": "ChatGPT Pro 20x",
                "access_status": "active",
                "renewal_enabled": False,
                "cancellation_scheduled": True,
                "cancellation_requested_at": "2026-09-28T12:35:00+02:00",
                "access_ends_on": "2026-10-11",
                "verified_at": "2026-09-28T12:37:00+02:00",
                "verified_source": "chatgpt.com Billing page (signed-in)",
            },
            {
                "email": "management@pitchai.net",
                "access_status": "active",
                "renewal_enabled": False,
                "cancellation_scheduled": True,
                "access_ends_on": "2026-09-20",
                "verified_at": "2026-09-18T10:00:00+02:00",
            },
            {
                "email": "security@pitchai.net",
                "access_status": "inactive",
                "renewal_enabled": False,
            },
            {
                "email": "mystery@pitchai.net",
                "card": "Mastercard testmask",
                "subscription_id": "must_not_leak",
            },
        ],
    }


@final
class SubscriptionAccountsTest(UsageTimeSeriesCase):
    """Prove subscription states come from verified flags, never guesses."""

    def write_snapshot(self, document: JsonObject, name: str = "subscriptions.json") -> Path:
        """Write one curated snapshot into the isolated test root.

        Returns:
            Path of the written snapshot file.
        """
        path = self.root / name
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def create_application(self, service: StaticCapacityService) -> Application:
        """Create the protected dashboard around one static capacity service.

        Returns:
            The composed dashboard application.
        """
        return create_scheduling_app(
            dashboard_settings(self.root),
            source=cast("StateSource", object()),
            service=cast("CapacityService", cast("object", service)),
        )

    def test_states_follow_verified_flags_and_keep_unknowns_unknown(self) -> None:
        """Derive display states from billing flags and drop unverified records."""
        path = self.write_snapshot(subscription_document())
        snapshot = read_snapshot(path, now=NOW)

        check_equal(snapshot["schema_version"], 1, "schema version")
        check_equal(snapshot["timezone"], "Europe/Berlin", "billing timezone")
        check_equal(snapshot["generated_at"], "2026-09-28T13:05:00+02:00", "generated at")
        check_equal(snapshot["error"], None, "error state")

        rows = cast("list[JsonObject]", snapshot["accounts"])
        identities = [row["email"] for row in rows]
        check_equal(
            identities,
            [
                "info@pitchai.net",
                "support@pitchai.net",
                "management@pitchai.net",
                "security@pitchai.net",
                "mystery@pitchai.net",
            ],
            "row identities",
        )
        check_equal(len(rows), 5, "row count")
        renewing = rows[0]
        cancelled = rows[1]
        ended = rows[2]
        inactive = rows[3]
        unstated = rows[4]
        check_equal(renewing["access_state"], "renewing", "protected renewal state")
        check(renewing["protected"] is True, "protected flag lost")
        check_equal(renewing["verified_age_days"], 11, "verified age")
        check(renewing["verified_stale"] is False, "fresh verification flagged stale")
        check_equal(cancelled["access_state"], "active_until_end", "cancelled access state")
        check(cancelled["renewal_enabled"] is False, "cancelled renewal flag")
        check_equal(
            cancelled["cancellation_requested_at"],
            "2026-09-28T12:35:00+02:00",
            "cancellation request moment",
        )
        check_equal(ended["access_state"], "access_ended", "ended access state")
        check_equal(inactive["access_state"], "inactive", "inactive subscription state")
        check_equal(unstated["access_state"], "unknown", "unstated state")
        check_equal(unstated["access_ends_on"], None, "invented access end")
        check_equal(unstated["renews_on"], None, "invented renewal date")
        check(unstated["verified_stale"] is True, "unverified record flagged fresh")
        check("must_not_leak" not in json.dumps(snapshot), "unexpected field escaped snapshot")

    def test_unusable_documents_and_rows_stay_unavailable(self) -> None:
        """Keep missing, broken, or oversized sources explicitly unavailable."""
        missing = read_snapshot(self.root / "absent.json", now=NOW)
        check_equal(missing["accounts"], [], "missing snapshot accounts")
        check_equal(missing["generated_at"], None, "missing snapshot generation")
        check_equal(missing["error"], UNAVAILABLE, "missing snapshot error")

        broken = self.root / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        check_equal(read_snapshot(broken, now=NOW)["accounts"], [], "broken snapshot accounts")

        wrong_version = self.write_snapshot(
            {"schema_version": 2, "accounts": [{"email": "someone@pitchai.net"}]},
            name="wrong-version.json",
        )
        check_equal(
            read_snapshot(wrong_version, now=NOW)["accounts"],
            [],
            "future schema accounts",
        )

        oversized = self.root / "oversized.json"
        oversized.write_text(" " * (MAX_SNAPSHOT_BYTES + 1), encoding="utf-8")
        check_equal(read_snapshot(oversized, now=NOW)["accounts"], [], "oversized snapshot")

        partial = self.write_snapshot(
            {
                "schema_version": 1,
                "accounts": [
                    {"email": "not-an-email", "access_status": "active"},
                    {
                        "email": "dated@pitchai.net",
                        "access_status": "active",
                        "renewal_enabled": True,
                        "access_ends_on": "soon",
                        "renews_on": "2026-13-45",
                        "verified_at": "2026-09-28 13:00:00",
                    },
                ],
            },
            name="partial.json",
        )
        rows = cast("list[JsonObject]", read_snapshot(partial, now=NOW)["accounts"])
        check_equal(len(rows), 1, "retained partial rows")
        check_equal(rows[0]["email"], "dated@pitchai.net", "retained row identity")
        check_equal(rows[0]["access_ends_on"], None, "unparsable access end")
        check_equal(rows[0]["renews_on"], None, "unparsable renewal date")
        check_equal(rows[0]["access_state"], "renewing", "partial renewal state")

    def test_endpoint_requires_pitchai_identity_and_serves_verified_rows(self) -> None:
        """Require one PitchAI operator identity and serve only curated facts."""
        path = self.write_snapshot(subscription_document())
        service = StaticCapacityService(operator_snapshot())
        environment = {SUBSCRIPTION_ACCOUNTS_FILE_ENVIRONMENT_VARIABLE: str(path)}
        with patch.dict(os.environ, environment), test_client_factory(
            self.create_application(service),
        ) as client:
            denied = client.get("/api/v1/subscription-accounts")
            foreign = client.get("/api/v1/subscription-accounts", headers=FOREIGN_HEADERS)
            response = client.get("/api/v1/subscription-accounts", headers=OPERATOR_HEADERS)
            check_equal(denied.status_code, int(HTTPStatus.UNAUTHORIZED), "missing identity")
            check_equal(foreign.status_code, int(HTTPStatus.UNAUTHORIZED), "foreign identity")
            check_equal(response.status_code, int(HTTPStatus.OK), "subscription status")
            payload = cast("JsonObject", response.json())
            check_equal(payload["error"], None, "endpoint error state")
            check("support@pitchai.net" in response.text, "verified account missing")
            check("must_not_leak" not in response.text, "unexpected field escaped endpoint")

    def test_endpoint_reports_unavailable_when_the_source_is_absent(self) -> None:
        """Keep a missing deployment source explicit instead of serving stale rows."""
        service = StaticCapacityService(operator_snapshot())
        missing = self.root / "absent-deployment.json"
        environment = {SUBSCRIPTION_ACCOUNTS_FILE_ENVIRONMENT_VARIABLE: str(missing)}
        with patch.dict(os.environ, environment), test_client_factory(
            self.create_application(service),
        ) as client:
            response = client.get("/api/v1/subscription-accounts", headers=OPERATOR_HEADERS)
            check_equal(response.status_code, int(HTTPStatus.OK), "availability status")
            payload = cast("JsonObject", response.json())
            check_equal(payload["accounts"], [], "unavailable accounts")
            check_equal(payload["error"], UNAVAILABLE, "unavailable error")
