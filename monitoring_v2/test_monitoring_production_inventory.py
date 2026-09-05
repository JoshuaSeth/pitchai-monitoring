# Copyright (c) 2026 PitchAI. All rights reserved.
"""Verify exact production domains, checks, alert policy, and runtime coverage."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from .domain_runtime import (
    inventory_runtime,
    load_domain_spec,
)
from .inventory import (
    EXPECTED_ACTIVE_DOMAINS,
    EXPECTED_DASHBOARD_ONLY_DOMAINS,
    EXPECTED_RETIRED_DOMAINS,
    REQUIRED_CONTAINER_NAMES,
    entry_by_domain,
    production_config,
    production_domains,
)
from .json_types import (
    json_object,
    object_list,
    optional_object,
    text_value,
    value_list,
)
from .testing_runtime import pytest

if TYPE_CHECKING:
    from .domain_runtime import AlertPolicy, DomainCheckSpec
    from .json_types import JsonInput

_EXPECTED_ACTIVE_DOMAIN_COUNT = 79
_EXPECTED_DATABASE_RULE_COUNT = 27
_EXPECTED_DOMAIN_GROUP_COUNT = 16
_EXPECTED_ROUTING_POLICY_COUNT = 3


def test_production_config_is_accepted_by_startup_validator() -> None:
    """Keep the deployed YAML compatible with service-monitoring startup."""
    config = production_config()
    inventory_runtime.validate_domain_inventory(config)


def test_authoritative_active_inventory_is_exact() -> None:
    """Require every live surface and reject disabled active inventory entries."""
    config = production_config()
    domains = production_domains()
    actual = {text_value(entry.get("domain")) for entry in domains}

    if frozenset(actual) != EXPECTED_ACTIVE_DOMAINS:
        pytest.fail("active production domain inventory changed")
    if not len(domains) == len(actual) == _EXPECTED_ACTIVE_DOMAIN_COUNT:
        pytest.fail("active production domain count changed")
    if len(optional_object(config.get("domain_groups"))) != _EXPECTED_DOMAIN_GROUP_COUNT:
        pytest.fail("domain group count changed")
    explicitly_disabled = [entry for entry in domains if entry.get("disabled") is True]
    explicitly_not_enabled = [entry for entry in domains if entry.get("enabled") is False]
    disabled_entries = [*explicitly_disabled, *explicitly_not_enabled]
    if disabled_entries:
        pytest.fail("disabled entry remained in active domain inventory")

    retired = object_list(config.get("retired_domains"))
    retired_names = {text_value(entry.get("domain")) for entry in retired}
    if frozenset(retired_names) != EXPECTED_RETIRED_DOMAINS:
        pytest.fail("explicitly excluded domain inventory changed")
    if len(retired) != len(retired_names) or retired_names.intersection(actual):
        pytest.fail("excluded domain inventory is duplicate or active")


def test_every_active_domain_has_an_executable_browser_contract() -> None:
    """Require a URL and at least one browser assertion for every active domain."""
    entries = production_domains()
    specs = [load_domain_spec(entry) for entry in entries]
    if len(specs) != len(EXPECTED_ACTIVE_DOMAINS):
        pytest.fail("an active domain lacked an executable contract")
    for spec in specs:
        if spec.domain not in EXPECTED_ACTIVE_DOMAINS:
            pytest.fail(f"unexpected executable contract: {spec.domain}")
        if not spec.url.startswith(("http://", "https://")):
            pytest.fail(f"unsafe contract URL: {spec.domain}")
        has_browser_assertion = bool(
            spec.required_selectors_all
            or spec.required_selectors_any
            or spec.required_text_all
            or spec.expected_title_contains,
        )
        if not has_browser_assertion:
            pytest.fail(f"{spec.domain} has no browser assertions")

    dft: dict[str, DomainCheckSpec] = {}
    for spec in specs:
        if spec.domain.endswith("formatief-toetsen.pitchai.net"):
            dft[spec.domain] = spec
    expected_dft = {
        "formatief-toetsen.pitchai.net",
        "staging.formatief-toetsen.pitchai.net",
    }
    if set(dft) != expected_dft:
        pytest.fail("DFT active contracts changed")
    if not all(spec.url.endswith("/healthz") for spec in dft.values()):
        pytest.fail("DFT readiness routes changed")


def test_alert_policy_routes_only_actionable_domains() -> None:
    """Keep expected or intentionally unused surfaces dashboard-only."""
    entries = production_domains()
    policies: dict[str, AlertPolicy] = {}
    for entry in entries:
        domain = text_value(entry.get("domain"))
        policies[domain] = inventory_runtime.parse_domain_alert_policy(entry)
    dashboard_only: set[str] = set()
    for domain, policy in policies.items():
        if not policy.telegram_enabled:
            dashboard_only.add(domain)
    if frozenset(dashboard_only) != EXPECTED_DASHBOARD_ONLY_DOMAINS:
        pytest.fail("dashboard-only domain policy changed")
    if not all(policies[domain].reason for domain in dashboard_only):
        pytest.fail("quiet domain lacks a reason")
    if not policies["pitchai.net"].telegram_enabled:
        pytest.fail("PitchAI production alerts were disabled")
    if not policies["dispatch.pitchai.net"].telegram_enabled:
        pytest.fail("Dispatcher production alerts were disabled")
    if not policies["aardappelprijs.nl"].telegram_enabled:
        pytest.fail("Aardappelprijs alerts were disabled")
    if text_value(entry_by_domain("aardappelprijs.nl").get("group")) != "potaito":
        pytest.fail("Aardappelprijs ownership group changed")


def test_formatiefleren_domains_preserve_launch_and_alert_contracts() -> None:
    """Keep the DFT marketing launch and canonical redirect actionable."""
    for domain in ("formatiefleren.nl", "www.formatiefleren.nl"):
        entry = entry_by_domain(domain)
        specification = load_domain_spec(entry)
        policy = inventory_runtime.parse_domain_alert_policy(entry)
        if text_value(entry.get("group")) != "dft":
            pytest.fail(f"DFT marketing domain escaped its owner group: {domain}")
        if specification.allowed_status_codes != [200]:
            pytest.fail(f"DFT marketing response contract changed: {domain}")
        check = optional_object(entry.get("check"))
        if text_value(check.get("expected_final_host_suffix")) != "formatiefleren.nl":
            pytest.fail(f"DFT marketing canonical host changed: {domain}")
        if specification.expected_title_contains != "DFT":
            pytest.fail(f"DFT marketing title readiness changed: {domain}")
        if specification.required_text_all != ["Formatief toetsen"]:
            pytest.fail(f"DFT marketing body readiness changed: {domain}")
        if not policy.telegram_enabled or policy.telegram != "critical":
            pytest.fail(f"DFT marketing downtime stopped alerting: {domain}")


def test_newly_discovered_domains_preserve_critical_contracts() -> None:
    """Keep every actionable 2026-08-27 discovery on normal incident routing."""
    expected = {
        "aigenda.pitchai.net": ("aigenda-calendar", [401]),
        "aigenda-monitor.pitchai.net": ("aigenda-calendar", [401]),
        "livedocuments.pitchai.net": ("platform-apps", [401]),
        "lfs.pitchai.net": ("infrastructure", [200]),
        "servers.pitchai.net": ("operations", [200]),
        "autopar-staging-web.37.27.67.52.nip.io": ("autopar", [200]),
        "unimixbrasil.com.br": ("unimix", [200]),
        "www.unimixbrasil.com.br": ("unimix", [200]),
    }
    for domain, (group, statuses) in expected.items():
        entry = entry_by_domain(domain)
        spec = load_domain_spec(entry)
        policy = inventory_runtime.parse_domain_alert_policy(entry)
        if text_value(entry.get("group")) != group:
            pytest.fail(f"discovered domain escaped its ownership group: {domain}")
        if spec.allowed_status_codes != statuses:
            pytest.fail(f"discovered domain response contract changed: {domain}")
        if not policy.telegram_enabled or policy.telegram != "critical":
            pytest.fail(f"discovered domain stopped normal incident routing: {domain}")

    alias_entry = entry_by_domain("theplanbook.pitchai.net")
    alias_spec = load_domain_spec(alias_entry)
    alias_policy = inventory_runtime.parse_domain_alert_policy(alias_entry)
    if alias_policy.telegram_enabled or alias_policy.telegram != "dashboard-only":
        pytest.fail("DePlanBook redirect alias became a duplicate incident route")
    alias_check = optional_object(alias_entry.get("check"))
    if text_value(alias_check.get("expected_final_host_suffix")) != "deplanbook.com":
        pytest.fail("DePlanBook redirect alias lost its canonical destination contract")
    if alias_spec.allowed_status_codes != [200]:
        pytest.fail("DePlanBook redirect alias final response contract changed")


def test_container_patterns_cover_production_runtime_dependencies() -> None:
    """Cover every socket-visible runtime while excluding transient jobs."""
    container_config = optional_object(production_config().get("container_health"))
    pattern_values = value_list(container_config.get("include_name_patterns"))
    patterns = [re.compile(text_value(value)) for value in pattern_values]
    uncovered = [name for name in REQUIRED_CONTAINER_NAMES if not any(pattern.search(name) for pattern in patterns)]
    uncovered.sort()
    if uncovered:
        pytest.fail(f"production containers are uncovered: {uncovered!r}")
    if any(pattern.search("autopar-batch-20260824") for pattern in patterns):
        pytest.fail("transient Autopar batch became required")
    if any(pattern.search("deplanbook-cms-canary") for pattern in patterns):
        pytest.fail("transient DePlanBook canary became required")


def test_afasask_entries_check_current_user_surfaces() -> None:
    """Keep production and demo AFASAsk contracts on their real user routes."""
    production_spec = load_domain_spec(entry_by_domain("afasask.gzb.nl"))
    if "mode=codex" not in production_spec.url:
        pytest.fail("AFASAsk production mode changed")
    if "intensity=medium" not in production_spec.url:
        pytest.fail("AFASAsk production intensity changed")
    if not any(item.selector == "#chat-input" for item in production_spec.required_selectors_all):
        pytest.fail("AFASAsk chat input assertion is missing")
    if not any(item.selector == ".chat-submit" for item in production_spec.required_selectors_all):
        pytest.fail("AFASAsk submit assertion is missing")
    if "Mislukt" in production_spec.forbidden_text_any:
        pytest.fail("obsolete AFASAsk failure assertion returned")

    demo_spec = load_domain_spec(entry_by_domain("demo.afasask.pitchai.net"))
    if "mode=codex" not in demo_spec.url:
        pytest.fail("AFASAsk demo mode changed")
    if "intensity=fast" not in demo_spec.url:
        pytest.fail("AFASAsk demo intensity changed")
    if not any(item.selector == "#main" for item in demo_spec.required_selectors_all):
        pytest.fail("AFASAsk demo main assertion is missing")
    if not any(item.selector == "text=/Login with AFAS/i" for item in demo_spec.required_selectors_all):
        pytest.fail("AFASAsk demo login assertion is missing")
    raw_checks = demo_spec.api_contract_checks
    checks = [json_object(cast("JsonInput", check)) for check in raw_checks]
    if not any(text_value(check.get("name")) == "codex_no_quota_readiness" for check in checks):
        pytest.fail("AFASAsk quota-readiness contract is missing")


def test_monitoring_config_exposes_database_dependency_rules() -> None:
    """Require the production database monitor policy to remain populated."""
    database_config = optional_object(production_config().get("database_dependencies"))
    if database_config.get("enabled") is not True:
        pytest.fail("database dependency monitoring is disabled")
    if len(object_list(database_config.get("rules"))) != _EXPECTED_DATABASE_RULE_COUNT:
        pytest.fail("database dependency rule count changed")
    if len(object_list(database_config.get("routing_policies"))) != _EXPECTED_ROUTING_POLICY_COUNT:
        pytest.fail("database routing policy count changed")
