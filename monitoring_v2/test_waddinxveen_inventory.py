# Copyright (c) 2026 PitchAI. All rights reserved.
"""Monitor the client demo without submitting chat or invoking a model."""

from __future__ import annotations

from .domain_runtime import inventory_runtime, load_domain_spec
from .inventory import entry_by_domain
from .json_types import optional_object
from .testing_runtime import pytest


def test_waddinxveen_demo_keeps_normal_alerts_and_read_only_checks() -> None:
    """Require the dedicated demo page and launcher, not an external website."""
    domain = "waddinxveen.demos.pitchai.net"
    entry = entry_by_domain(domain)
    spec = load_domain_spec(entry)
    policy = inventory_runtime.parse_domain_alert_policy(entry)
    check = optional_object(entry.get("check"))
    if entry.get("environment") != "demo" or entry.get("owner_project") != "quickchat":
        pytest.fail("client demo ownership/environment drifted")
    if spec.url != f"https://{domain}/waddinxveen/demo" or not spec.browser_enabled:
        pytest.fail("demo must verify its real public page")
    if check.get("expected_final_path") != "/waddinxveen/demo" or spec.allowed_status_codes != [200]:
        pytest.fail("demo route contract drifted")
    if spec.synthetic_transactions or spec.api_contract_checks:
        pytest.fail("availability check must not submit chat or invoke a model")
    if not any(item.selector == "#open-chat" for item in spec.required_selectors_all):
        pytest.fail("demo launcher must be present")
    if not policy.telegram_enabled or policy.telegram != "critical":
        pytest.fail("client-facing demo must retain normal alerts")
