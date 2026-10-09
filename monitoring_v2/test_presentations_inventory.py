# Copyright (c) 2026 PitchAI. All rights reserved.
"""Protect private presentation availability without reading client material."""

from __future__ import annotations

from .domain_runtime import inventory_runtime, load_domain_spec
from .inventory import entry_by_domain
from .json_types import optional_object, text_value
from .testing_runtime import pytest


def test_private_presentations_check_denial_and_page_only_once() -> None:
    """Pin credential-free access denial and keep duplicate aliases quiet."""
    domains = {
        "presentaties.pitchai.net": True,
        "presentations.pitchai.net": False,
        "presentations.135-181-182-48.sslip.io": False,
    }
    for domain, alertable in domains.items():
        entry = entry_by_domain(domain)
        spec = load_domain_spec(entry)
        check = optional_object(entry.get("check"))
        policy = inventory_runtime.parse_domain_alert_policy(entry)
        if spec.url != f"https://{domain}/oudijk/" or spec.allowed_status_codes != [401]:
            pytest.fail(f"private presentation access-denial contract changed: {domain}")
        if spec.browser_enabled or spec.required_text_all != ["401 Authorization Required"]:
            pytest.fail(f"presentation probe gained content access: {domain}")
        if text_value(check.get("expected_final_host_suffix")) != domain:
            pytest.fail(f"presentation probe may redirect outside its host: {domain}")
        if text_value(check.get("expected_final_path")) != "/oudijk/":
            pytest.fail(f"presentation probe may follow an unrelated route: {domain}")
        if spec.api_contract_checks or check.get("synthetic") or check.get("headers"):
            pytest.fail(f"presentation probe gained credentials or transactions: {domain}")
        if policy.telegram_enabled != alertable:
            pytest.fail(f"canonical presentation/alias incident policy changed: {domain}")
        if not alertable and (policy.telegram != "dashboard-only" or not policy.reason):
            pytest.fail(f"presentation alias lost its explicit quiet reason: {domain}")
