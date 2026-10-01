# Copyright (c) 2026 PitchAI. All rights reserved.
"""Keep the pre-launch recorder visible without private-data probes or alerts."""

from __future__ import annotations

from .domain_runtime import inventory_runtime, load_domain_spec
from .inventory import entry_by_domain
from .json_types import optional_object
from .testing_runtime import pytest


def test_wrist_vault_uses_quiet_unauthenticated_read_only_contract() -> None:
    """Check only the public authentication boundary, never recording routes."""
    domain = "wrist-vault.135-181-182-48.sslip.io"
    entry = entry_by_domain(domain)
    spec = load_domain_spec(entry)
    policy = inventory_runtime.parse_domain_alert_policy(entry)
    check = optional_object(entry.get("check"))
    if entry.get("environment") != "staging" or entry.get("group") != "infrastructure":
        pytest.fail("pre-launch recorder ownership/environment drifted")
    if spec.url != f"https://{domain}/" or spec.browser_enabled:
        pytest.fail("recorder must use only a bounded public HTTP GET")
    if spec.allowed_status_codes != [401] or check.get("expected_final_host_suffix") != domain:
        pytest.fail("recorder authentication boundary drifted")
    if len(spec.api_contract_checks) != 1:
        pytest.fail("recorder must have exactly one authentication contract")
    contract = optional_object(spec.api_contract_checks[0])
    if contract.get("path") != "/" or contract.get("expected_status_codes") != [401]:
        pytest.fail("recorder probe must not access recording routes")
    if contract.get("json_paths_equal") != {"error": "authentication required"}:
        pytest.fail("recorder JSON authentication contract drifted")
    if policy.telegram_enabled or policy.telegram != "dashboard-only" or not policy.reason:
        pytest.fail("pre-launch recorder must remain explicitly alert-disabled")
