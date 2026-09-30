# Copyright (c) 2026 PitchAI. All rights reserved.
"""Reviewed subscription snapshot IO and OAuth affinity proofs."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import patch
from uuid import uuid4

from .clients import BrokerProviderSource
from .expiry_source import ExpiryAwareSource
from .models import ProviderCredentials
from .subscription_expiry import confirmed_end_date, read_subscription_expiry
from .test_organization_support import NOW, account_observation, require_equal

if TYPE_CHECKING:
    from pathlib import Path


def test_refresh_rereads_snapshot_without_changing_oauth_affinity(tmp_path: Path) -> None:
    """Evidence changes reach the final recheck while credentials stay account-bound."""
    path = tmp_path / "subscriptions.json"
    observation = replace(
        account_observation("account@example.test"),
        credentials=ProviderCredentials(access_token=uuid4().hex, account_id="original-tenant"),
    )
    source = ExpiryAwareSource(broker_url="http://broker.invalid", broker_admin_token=uuid4().hex)
    with (
        patch("auth_reset_guardian.subscription_expiry.SUBSCRIPTION_FILE", path),
        patch.object(BrokerProviderSource, "refresh_account", return_value=observation),
    ):
        for day in ("2026-09-10", "2026-09-11"):
            document = {
                "schema_version": 1, "timezone": "Europe/Berlin", "accounts": [{
                    "email": observation.descriptor.label, "access_status": "active",
                    "renewal_enabled": False, "access_ends_on": day,
                    "verified_at": NOW.isoformat(), "verified_source": "billing review",
                }],
            }
            _ = path.write_text(json.dumps(document), encoding="utf-8")
            refreshed = source.refresh_account(observation.descriptor)
            require_equal(refreshed.credentials, observation.credentials)
            require_equal(refreshed.descriptor, observation.descriptor)
            require_equal(confirmed_end_date(refreshed), day)


def test_missing_snapshot_is_explicitly_unknown(tmp_path: Path) -> None:
    """A missing billing file never manufactures an expiry from provider quota."""
    with patch("auth_reset_guardian.subscription_expiry.SUBSCRIPTION_FILE", tmp_path / "absent.json"):
        result = read_subscription_expiry("account@example.test", now=NOW)
    require_equal(result["subscription_access_ends_on"], None)
