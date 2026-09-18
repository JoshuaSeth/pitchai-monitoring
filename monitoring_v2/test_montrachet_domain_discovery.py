# Copyright (c) 2026 PitchAI. All rights reserved.
"""Keep the dedicated client demo visible with an honest direct-serve contract."""

from __future__ import annotations

from .domain_runtime import inventory_runtime, load_domain_spec
from .inventory import entry_by_domain
from .json_types import optional_object, text_value
from .testing_runtime import pytest


def test_montrachet_demo_monitors_public_origin_with_normal_alerts() -> None:
    """Require the live dedicated origin without invoking authenticated voice."""
    entry = entry_by_domain("montrachet-demo.pitchai.net")
    spec = load_domain_spec(entry)
    policy = inventory_runtime.parse_domain_alert_policy(entry)
    check = optional_object(entry.get("check"))
    if text_value(entry.get("environment")) != "production":
        pytest.fail("client-facing demo must retain production signal coverage")
    if text_value(entry.get("group")) != "learning-demos":
        pytest.fail("client demo ownership group drifted")
    if spec.url != "https://montrachet-demo.pitchai.net/" or spec.browser_enabled:
        pytest.fail("demo must use the bounded anonymous HTTP edge check")
    if spec.allowed_status_codes != [200]:
        pytest.fail("public demo landing page must answer successfully")
    if check.get("expected_final_host_suffix") != "montrachet-demo.pitchai.net":
        pytest.fail("public demo must keep answering from its own origin, not an SSO edge")
    if text_value(check.get("expected_title_contains")) != "Montrachet":
        pytest.fail("public demo landing page contract drifted")
    missing_selectors = check.get("required_selectors_all")
    if missing_selectors != [{"selector": "body", "state": "attached"}]:
        pytest.fail("demo must retain the bounded landing-page selector contract")
    if spec.api_contract_checks:
        pytest.fail("anonymous availability must not invoke authenticated voice")
    if policy.telegram != "critical" or not policy.telegram_enabled:
        pytest.fail("important client demo lost normal alert behavior")
