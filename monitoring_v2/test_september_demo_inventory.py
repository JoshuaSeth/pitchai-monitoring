# Copyright (c) 2026 PitchAI. All rights reserved.
"""Protect read-only demo availability and private review access boundaries."""

from __future__ import annotations

from .domain_runtime import inventory_runtime, load_domain_spec
from .inventory import entry_by_domain
from .testing_runtime import pytest


def test_firebase_preview_remains_visible_without_paging() -> None:
    """Cover the live Firebase preview without activating the unprovisioned alias."""
    domain = "apologetica-react-staging.web.app"
    entry = entry_by_domain(domain)
    spec = load_domain_spec(entry)
    policy = inventory_runtime.parse_domain_alert_policy(entry)
    if spec.url != f"https://{domain}/" or spec.allowed_status_codes != [200]:
        pytest.fail("Firebase preview availability contract drifted")
    if spec.expected_title_contains != "Geloofsverdediging.nl" or spec.browser_enabled:
        pytest.fail("Firebase preview must retain its read-only shell check")
    if policy.telegram_enabled or policy.telegram != "dashboard-only" or not policy.reason:
        pytest.fail("historical Firebase preview must remain explicitly quiet")


def test_salesengine_checks_public_shell_without_starting_calls() -> None:
    """Keep the public demo alertable without executing paid voice work."""
    domain = "salesengine.demos.pitchai.net"
    entry = entry_by_domain(domain)
    spec = load_domain_spec(entry)
    policy = inventory_runtime.parse_domain_alert_policy(entry)
    if spec.url != f"https://{domain}/" or spec.browser_enabled or spec.api_contract_checks:
        pytest.fail("SalesEngine monitoring must only GET the public shell")
    if spec.allowed_status_codes != [200] or spec.expected_title_contains != "Ember Duplex":
        pytest.fail("SalesEngine public availability contract drifted")
    if not policy.telegram_enabled or policy.telegram != "critical":
        pytest.fail("SalesEngine demo must retain normal incident routing")


def test_private_reviews_stay_quiet_and_never_use_personal_links() -> None:
    """Expect intentional denial without accessing private media or credentials."""
    for name, title in (("gzb", "GZB Review"), ("jeugdtandarts", "Jeugdtandarts Review")):
        domain = f"{name}-review.135-181-182-48.sslip.io"
        entry = entry_by_domain(domain)
        spec = load_domain_spec(entry)
        policy = inventory_runtime.parse_domain_alert_policy(entry)
        if spec.url != f"https://{domain}/" or spec.browser_enabled or spec.api_contract_checks:
            pytest.fail("private review monitoring must only GET the credential-free root")
        if spec.allowed_status_codes != [403] or spec.expected_title_contains != title:
            pytest.fail("private review denial contract drifted")
        if spec.required_text_all != ["Deze reviewruimte is privé."]:
            pytest.fail("private review must assert its actual access boundary")
        if policy.telegram_enabled or policy.telegram != "dashboard-only" or not policy.reason:
            pytest.fail("private review must never create Telegram noise")
