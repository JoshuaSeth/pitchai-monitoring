# Copyright (c) 2026 PitchAI. All rights reserved.
"""Legacy reports and scheduling metadata cannot establish execution exhaustion."""

from __future__ import annotations

from .execution_exhaustion import BrokerExecutionDocument, execution_failure_evidence
from .test_organization_support import NOW, require_equal


def test_legacy_or_outcome_only_reports_never_qualify() -> None:
    """Neither a refreshed probe time nor a timestamped generic outcome is proof."""
    legacy: dict[str, object] = {
        "last_reported_outcome": "usage_limit_reached", "last_probe_at": NOW.isoformat(),
        "availability": "rate_limited",
    }
    outcome_only: dict[str, object] = {
        "schema_version": 1, "source": "authenticated_lease_report", "outcome": "usage_limit_reached",
        "observed_at": NOW.isoformat(), "account_id": "account", "lease_id": "lease", "client_name": "client",
    }
    for state in (legacy, {**legacy, "execution_exhaustion": outcome_only}):
        require_equal(execution_failure_evidence({"state": state}, account_id="account") is None, expected=True)


def test_mismatched_account_and_nonexecution_errors_never_qualify() -> None:
    """A lease report must opt into the actual execution error contract."""
    proof: dict[str, object] = {
        "schema_version": 1, "source": "provider_execution_error", "error_code": "usage_limit_reached",
        "occurred_at": NOW.isoformat(), "received_at": NOW.isoformat(),
        "account_id": "account", "lease_id": "lease", "client_name": "client",
    }
    for change in (
        {"account_id": "another-account"}, {"source": "cached_broker_status"},
        {"error_code": "rate_limited"}, {"schema_version": True}, {"schema_version": 2},
        {"client_name": ""}, {"lease_id": None},
    ):
        payload = BrokerExecutionDocument(state={"execution_exhaustion": {**proof, **change}})
        require_equal(execution_failure_evidence(payload, account_id="account") is None, expected=True)
