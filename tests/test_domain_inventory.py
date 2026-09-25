# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tests for test domain inventory behavior."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import TYPE_CHECKING

import pytest

from domain_checks.inventory import validate_domain_inventory
from domain_checks.main import load_domain_spec
from domain_checks.testing import verify
from tests.config_inventory_expectations import domain_configs, production_config

if TYPE_CHECKING:
    from typing import Literal

    from domain_checks.types import JsonObject, JsonValue


def _valid_config() -> JsonObject:
    return {
        "inventory": {
            "version": 1,
            "reviewed_at": "2026-08-24",
            "authoritative_sources": ["authoritative DNS", "active ingress"],
        },
        "domain_groups": {
            "core": {
                "label": "PitchAI core",
                "description": "Primary public platform routes",
                "order": 10,
            },
        },
        "container_health": {
            "enabled": True,
            "include_name_patterns": ["^service-monitoring$"],
        },
        "domains": [
            {
                "domain": "pitchai.net",
                "label": "PitchAI website",
                "group": "core",
                "environment": "production",
                "kind": "application",
                "sources": ["authoritative DNS", "active ingress"],
                "check": {
                    "url": "https://pitchai.net",
                    "required_selectors_all": ["body"],
                },
            },
        ],
        "retired_domains": [
            {
                "domain": "old.pitchai.net",
                "classification": "retired",
                "reason": "No current DNS or ingress contract",
                "sources": ["authoritative DNS", "active ingress"],
            },
        ],
    }


def test_domain_inventory_validation_accepts_complete_metadata() -> None:
    """Verify domain inventory validation accepts complete metadata."""
    config = _valid_config()
    validate_domain_inventory(config)


@pytest.mark.parametrize(
    ("section", "key", "value", "operation", "message"),
    [
        ("domains", "group", None, "delete", "domains[0].group is required"),
        ("domains", "group", "missing", "replace", "unknown group"),
        ("domains", "sources", None, "delete", "sources must be a non-empty list"),
        (
            "retired_domains",
            "domain",
            "pitchai.net",
            "replace",
            "active and retired inventory",
        ),
        (
            "container_health",
            "include_name_patterns",
            ["["],
            "replace",
            "include_name_patterns[0] is invalid",
        ),
        (
            "domains",
            "alert_policy",
            {"telegram": "silent", "reason": "invalid mode"},
            "replace",
            "alert_policy.telegram must be one of",
        ),
        (
            "domains",
            "alert_policy",
            {"telegram": "dashboard-only"},
            "replace",
            "reason is required for dashboard-only domains",
        ),
    ],
)
def test_domain_inventory_validation_fails_loudly(
    section: Literal["domains", "retired_domains", "container_health"],
    key: str,
    value: JsonValue,
    operation: Literal["delete", "replace"],
    message: str,
) -> None:
    """Verify domain inventory validation fails loudly."""
    config = deepcopy(_valid_config())
    raw_target = config.get(section)
    if section == "container_health":
        if not isinstance(raw_target, dict):
            pytest.fail("Expected container-health mapping")
        target = raw_target
    else:
        if (
            not isinstance(raw_target, list)
            or not raw_target
            or not isinstance(raw_target[0], dict)
        ):
            pytest.fail(f"Expected non-empty {section} mapping list")
        target = raw_target[0]
    if operation == "delete":
        _ = target.pop(key, None)
    else:
        target[key] = value
    with pytest.raises(ValueError, match=re.escape(message)):
        validate_domain_inventory(config)


def test_afasask_domains_are_enabled_and_check_current_user_surfaces() -> None:
    """Verify afasask domains are enabled and check current user surfaces."""
    domains = domain_configs(production_config())

    entry = next(
        (domain for domain in domains if domain.get("domain") == "afasask.gzb.nl"), None,
    )
    if entry is None:
        pytest.fail("Missing afasask.gzb.nl domain config")
    verify(entry.get("disabled") is not True)

    spec = load_domain_spec(entry)
    selector_names = [item.selector for item in spec.required_selectors_all]
    verify("mode=codex" in spec.url)
    verify("intensity=medium" in spec.url)
    verify("#chat-input" in selector_names)
    verify(".chat-submit" in selector_names)
    verify("Mislukt" not in spec.forbidden_text_any)

    demo_entry = next(
        (
            domain
            for domain in domains
            if domain.get("domain") == "demo.afasask.pitchai.net"
        ),
        None,
    )
    if demo_entry is None:
        pytest.fail("Missing demo.afasask.pitchai.net domain config")
    verify(demo_entry.get("disabled") is not True)

    demo_spec = load_domain_spec(demo_entry)
    demo_selector_names = [item.selector for item in demo_spec.required_selectors_all]
    api_check_names = [check.get("name") for check in demo_spec.api_contract_checks]
    verify("mode=codex" in demo_spec.url)
    verify("intensity=fast" in demo_spec.url)
    verify("#main" in demo_selector_names)
    verify("text=/Login with AFAS/i" in demo_selector_names)
    verify("codex_no_quota_readiness" in api_check_names)
