# Copyright (c) 2026 PitchAI. All rights reserved.
"""Protect the public launches discovered in the September 5 inventory sweep."""

from __future__ import annotations

from .domain_runtime import inventory_runtime, load_domain_spec
from .inventory import entry_by_domain
from .json_types import optional_object, text_value
from .testing_runtime import pytest


def test_september_launches_keep_actionable_routes_and_ownership() -> None:
    """Monitor independent production and client-demo routes without aliases."""
    expected = {
        "agents.pitchai.net": ("corporate", "/", "PitchAI Agent Engine"),
        "crm.pitchai.net": ("operations", "/crm", None),
        "nl241-satellite-data-portal.demos.pitchai.net": (
            "learning-demos", "/", "Satellietdataportaal",
        ),
        "rijkscatering.demos.pitchai.net": (
            "learning-demos", "/", "Rijkscatering Monitor",
        ),
    }
    for domain, (group, route, title) in expected.items():
        entry = entry_by_domain(domain)
        spec = load_domain_spec(entry)
        policy = inventory_runtime.parse_domain_alert_policy(entry)
        check = optional_object(entry.get("check"))
        final_host = "login.microsoftonline.com" if domain == "crm.pitchai.net" else domain
        if text_value(entry.get("group")) != group:
            pytest.fail(f"launch ownership changed: {domain}")
        if spec.url != f"https://{domain}{route}" or spec.allowed_status_codes != [200]:
            pytest.fail(f"launch route/status contract changed: {domain}")
        if text_value(check.get("expected_final_host_suffix")) != final_host:
            pytest.fail(f"launch redirect contract changed: {domain}")
        if title is not None and spec.expected_title_contains != title:
            pytest.fail(f"launch page identity changed: {domain}")
        if not policy.telegram_enabled or policy.telegram != "critical":
            pytest.fail(f"important launch lost normal incident behavior: {domain}")


def test_preview_and_bootstrap_alias_remain_quiet() -> None:
    """Keep isolated previews visible and prevent duplicate canonical paging."""
    expected = {
        "apol.135-181-182-48.sslip.io": "/",
        "route-anchor.135-181-182-48.sslip.io": "/healthz",
    }
    for domain, route in expected.items():
        entry = entry_by_domain(domain)
        spec = load_domain_spec(entry)
        policy = inventory_runtime.parse_domain_alert_policy(entry)
        if spec.url != f"https://{domain}{route}" or spec.allowed_status_codes != [200]:
            pytest.fail(f"quiet surface contract changed: {domain}")
        if policy.telegram_enabled or policy.telegram != "dashboard-only" or not policy.reason:
            pytest.fail(f"quiet surface became an incident source: {domain}")
    canonical = inventory_runtime.parse_domain_alert_policy(entry_by_domain("route-anchor.pitchai.net"))
    if not canonical.telegram_enabled:
        pytest.fail("canonical Route Anchor lost normal incident behavior")
