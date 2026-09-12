# Copyright (c) 2026 PitchAI. All rights reserved.
"""Protect production MCP coverage and the isolated comparison's quiet policy."""

from __future__ import annotations

from .domain_runtime import inventory_runtime, load_domain_spec
from .inventory import entry_by_domain
from .json_types import optional_object, text_value
from .testing_runtime import pytest


def test_mcp_surfaces_have_bounded_http_contracts_and_distinct_policies() -> None:
    """Require exact metadata values without a browser or effectful MCP call."""
    expected = {
        "host-mcp.135-181-182-48.sslip.io": (
            "/healthz", "production", "critical",
            {"ok": True, "service": "pitchai-host-mcp"},
        ),
        "webcodex.135-181-182-48.sslip.io": (
            "/.well-known/oauth-authorization-server", "staging", "dashboard-only",
            {
                "issuer": "https://webcodex.135-181-182-48.sslip.io",
                "authorization_endpoint": "https://webcodex.135-181-182-48.sslip.io/oauth/authorize",
            },
        ),
    }
    for domain, (path, environment, mode, values) in expected.items():
        entry = entry_by_domain(domain)
        spec = load_domain_spec(entry)
        policy = inventory_runtime.parse_domain_alert_policy(entry)
        if text_value(entry.get("group")) != "infrastructure":
            pytest.fail(f"MCP ownership group drifted: {domain}")
        if text_value(entry.get("environment")) != environment:
            pytest.fail(f"MCP environment drifted: {domain}")
        if spec.browser_enabled or spec.url != f"https://{domain}{path}":
            pytest.fail(f"MCP read-only HTTP route drifted: {domain}")
        if spec.allowed_status_codes != [200] or spec.expected_final_host_suffix != domain:
            pytest.fail(f"MCP HTTP response contract drifted: {domain}")
        if len(spec.api_contract_checks) != 1:
            pytest.fail(f"MCP JSON contract disappeared: {domain}")
        contract = optional_object(spec.api_contract_checks[0])
        if contract.get("path") != path or contract.get("json_paths_equal") != values:
            pytest.fail(f"MCP JSON identity/readiness contract drifted: {domain}")
        if policy.telegram != mode or policy.telegram_enabled != (mode == "critical"):
            pytest.fail(f"MCP alert policy drifted: {domain}")
        if mode == "dashboard-only" and not policy.reason:
            pytest.fail("comparison endpoint lost its explicit quiet reason")
