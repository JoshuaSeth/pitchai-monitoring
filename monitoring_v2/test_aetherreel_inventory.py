# Copyright (c) 2026 PitchAI. All rights reserved.
"""Keep the unfinished streaming platform visible without alerting."""

from __future__ import annotations

from .domain_runtime import inventory_runtime, load_domain_spec
from .inventory import entry_by_domain
from .json_types import optional_object
from .testing_runtime import pytest


def test_aetherreel_prelaunch_checks_are_quiet_and_read_only() -> None:
    """Check the public shell without playback, uploads, login or payments."""
    domain = "aetherreel.37.27.67.52.nip.io"
    entry = entry_by_domain(domain)
    spec = load_domain_spec(entry)
    policy = inventory_runtime.parse_domain_alert_policy(entry)
    check = optional_object(entry.get("check"))
    if entry.get("environment") != "staging":
        pytest.fail("pre-launch platform environment drifted")
    if spec.url != f"https://{domain}/" or spec.allowed_status_codes != [200]:
        pytest.fail("public homepage contract drifted")
    if check.get("synthetic_transactions") or spec.api_contract_checks:
        pytest.fail("availability check must not trigger account or media operations")
    if policy.telegram_enabled or policy.telegram != "dashboard-only" or not policy.reason:
        pytest.fail("pre-launch platform must remain explicitly quiet")
