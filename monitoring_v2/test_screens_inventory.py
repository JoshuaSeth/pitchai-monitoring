# Copyright (c) 2026 PitchAI. All rights reserved.
"""Keep screen-support staging visible without alerts or support sessions."""

from __future__ import annotations

from .domain_runtime import inventory_runtime, load_domain_spec
from .inventory import entry_by_domain
from .json_types import optional_object
from .testing_runtime import pytest


def test_screens_uses_only_quiet_read_only_health() -> None:
    """Never enroll a device, share a screen, or open a support session."""
    domain = "screens.135-181-182-48.sslip.io"
    entry = entry_by_domain(domain)
    spec = load_domain_spec(entry)
    policy = inventory_runtime.parse_domain_alert_policy(entry)
    if entry.get("environment") != "staging" or entry.get("group") != "infrastructure":
        pytest.fail("screen-support test-service classification drifted")
    if spec.url != f"https://{domain}/health" or spec.browser_enabled:
        pytest.fail("screen-support monitoring must use only public HTTP health")
    if spec.allowed_status_codes != [200] or len(spec.api_contract_checks) != 1:
        pytest.fail("screen-support must expose exactly one healthy API contract")
    contract = optional_object(spec.api_contract_checks[0])
    if contract.get("path") != "/health" or contract.get("expected_status_codes") != [200]:
        pytest.fail("screen-support probe must not access support-session routes")
    if contract.get("json_paths_equal") != {"ok": True}:
        pytest.fail("screen-support health contract drifted")
    if policy.telegram_enabled or policy.telegram != "dashboard-only" or not policy.reason:
        pytest.fail("pre-launch screen-support must remain explicitly alert-disabled")
