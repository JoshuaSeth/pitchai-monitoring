# Copyright (c) 2026 PitchAI. All rights reserved.
"""Keep Route Anchor health checks on their machine-readable HTTP contract."""

from __future__ import annotations

from .domain_runtime import inventory_runtime, load_domain_spec
from .inventory import entry_by_domain, production_config
from .testing_runtime import pytest


def test_route_anchor_health_checks_are_http_only() -> None:
    """Do not turn JSON endpoint rendering into an availability dependency."""
    config = production_config()
    inventory_runtime.validate_domain_inventory(config)
    expected_urls = {
        "route-anchor.pitchai.net": "https://route-anchor.pitchai.net/healthz",
        "route-anchor.135-181-182-48.sslip.io": (
            "https://route-anchor.135-181-182-48.sslip.io/healthz"
        ),
    }

    for domain, expected_url in expected_urls.items():
        specification = load_domain_spec(entry_by_domain(domain))
        if specification.url != expected_url:
            pytest.fail(f"Route Anchor health URL changed: {domain}")
        if specification.allowed_status_codes != [200]:
            pytest.fail(f"Route Anchor HTTP status contract changed: {domain}")
        if specification.browser_enabled:
            pytest.fail(f"Route Anchor health check renders a browser: {domain}")
        if not {"status", "ok"}.issubset(specification.required_text_all):
            pytest.fail(f"Route Anchor health identity weakened: {domain}")
