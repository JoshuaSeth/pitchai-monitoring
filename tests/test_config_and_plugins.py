# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tests for test config and plugins behavior."""

from __future__ import annotations

import asyncio
import re
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

import httpx
import pytest

import domain_checks.main as monitoring
from domain_checks.inventory import validate_domain_inventory
from domain_checks.main import (
    check_one_domain,
    load_domain_spec,
    normalize_domain_entries,
    route_domain_telegram_alert,
)
from domain_checks.telegram import TelegramConfig
from domain_checks.testing import verify
from tests.config_inventory_expectations import (
    EXPECTED_ACTIVE_DOMAIN_COUNT,
    EXPECTED_ACTIVE_DOMAINS,
    EXPECTED_DOMAIN_GROUP_COUNT,
    REQUIRED_RUNTIME_DEPENDENCIES,
    domain_configs,
    production_config,
)

if TYPE_CHECKING:
    from playwright.async_api import Browser

    from domain_checks.common_check import DomainCheckSpec
    from domain_checks.types import JsonObject

EXPECTED_DASHBOARD_ONLY_DOMAINS = {
    "registry.pitchai.net",
    "agentcloud.pitchai.net",
    "dashboards.pitchai.net",
    "support.pitchai.net",
    "cursussen.pitchai.net",
}


def test_all_config_domains_have_check_specs() -> None:
    """Verify all config domains have check specs."""
    config = production_config()
    validate_domain_inventory(config)
    domains = domain_configs(config)

    specs = [load_domain_spec(entry) for entry in domains]
    verify(len(specs) == len(domains))

    for spec in specs:
        verify(spec.domain)
        verify(spec.url.startswith(("http://", "https://")))
        has_any_assertion = bool(
            spec.required_selectors_all
            or spec.required_selectors_any
            or spec.required_text_all
            or spec.expected_title_contains,
        )
        verify(has_any_assertion, f"{spec.domain} has no browser assertions")


def test_authoritative_active_inventory_is_exact_and_dft_is_enabled() -> None:
    """Verify authoritative active inventory is exact and dft is enabled."""
    config = production_config()
    domains = domain_configs(config)
    actual = {str(entry["domain"]) for entry in domains}

    verify(actual == EXPECTED_ACTIVE_DOMAINS)
    verify(len(domains) == len(actual) == EXPECTED_ACTIVE_DOMAIN_COUNT)
    domain_groups = config.get("domain_groups")
    if not isinstance(domain_groups, dict):
        pytest.fail("Expected domain_groups mapping")
    verify(len(domain_groups) == EXPECTED_DOMAIN_GROUP_COUNT)
    verify(
        not [
            entry
            for entry in domains
            if entry.get("disabled") or entry.get("enabled") is False
        ],
    )

    dft_entries = [entry for entry in domains if entry["group"] == "dft"]
    dft = {entry["domain"]: load_domain_spec(entry) for entry in dft_entries}
    verify(
        set(dft)
        == {
            "formatief-toetsen.pitchai.net",
            "staging.formatief-toetsen.pitchai.net",
            "dft-marketing-staging.pitchai.net",
        },
    )
    verify(dft["formatief-toetsen.pitchai.net"].url.endswith("/healthz"))
    verify(dft["staging.formatief-toetsen.pitchai.net"].url.endswith("/healthz"))


def test_alert_policy_has_only_the_five_explicit_dashboard_only_domains() -> None:
    """Verify alert policy has only the five explicit dashboard only domains."""
    config = production_config()
    domains = domain_configs(config)
    entries = normalize_domain_entries(domains)
    entries_by_domain = {entry.domain: entry for entry in entries}
    dashboard_entries = [
        entry for entry in entries if entry.domain in EXPECTED_DASHBOARD_ONLY_DOMAINS
    ]
    dashboard_domains = {entry.domain for entry in dashboard_entries}
    dashboard_reasons = [entry.alert_policy.reason for entry in dashboard_entries]

    verify(dashboard_domains == EXPECTED_DASHBOARD_ONLY_DOMAINS)
    verify(all(dashboard_reasons))
    verify(entries_by_domain["pitchai.net"].routes_telegram is True)
    verify(entries_by_domain["dispatch.pitchai.net"].routes_telegram is True)
    verify(entries_by_domain["aardappelprijs.nl"].routes_telegram is True)

    inventory_by_domain = {str(entry["domain"]): entry for entry in domains}
    verify(inventory_by_domain["aardappelprijs.nl"]["group"] == "potaito")


@pytest.mark.asyncio
async def test_domain_telegram_router_suppresses_dashboard_only_and_routes_critical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify domain telegram router suppresses dashboard only and routes critical."""
    domains = domain_configs(production_config())
    normalized_entries = normalize_domain_entries(domains)
    entries = {entry.domain: entry for entry in normalized_entries}
    sent: list[str] = []

    async def fake_send(
        client: httpx.AsyncClient,
        config: TelegramConfig,
        message: str,
    ) -> tuple[bool, list[JsonObject]]:
        _ = client, config
        await asyncio.sleep(0)
        sent.append(message)
        return True, [{"ok": True}]

    monkeypatch.setattr(monitoring, "send_telegram_message_chunked", fake_send)
    telegram_cfg = TelegramConfig(bot_token="", chat_id="")

    async with httpx.AsyncClient() as client:
        for domain in sorted(EXPECTED_DASHBOARD_ONLY_DOMAINS):
            routed = await route_domain_telegram_alert(
                http_client=client,
                telegram_cfg=telegram_cfg,
                entry=entries[domain],
                message=f"down: {domain}",
            )
            verify(routed is None)

        verify(not sent)

        routed = await route_domain_telegram_alert(
            http_client=client,
            telegram_cfg=telegram_cfg,
            entry=entries["pitchai.net"],
            message="down: pitchai.net",
        )
    verify(routed == (True, [{"ok": True}]))
    verify(sent == ["down: pitchai.net"])


def test_container_health_patterns_cover_every_socket_visible_runtime_dependency() -> (
    None
):
    """Verify container health patterns cover every socket visible runtime dependency."""
    container_health = production_config().get("container_health")
    if not isinstance(container_health, dict):
        pytest.fail("Expected container_health mapping")
    raw_patterns = container_health.get("include_name_patterns")
    if not isinstance(raw_patterns, list):
        pytest.fail("Expected container-health include patterns")
    patterns: list[re.Pattern[str]] = []
    for raw_pattern in raw_patterns:
        if not isinstance(raw_pattern, str):
            pytest.fail(f"Expected string container pattern, got {raw_pattern!r}")
        patterns.append(re.compile(raw_pattern))
    uncovered: list[str] = []
    for name in REQUIRED_RUNTIME_DEPENDENCIES:
        matches = [pattern.search(name) for pattern in patterns]
        if not any(matches):
            uncovered.append(name)
    uncovered.sort()
    autopar_matches = [pattern.search("autopar-batch-20260824") for pattern in patterns]
    canary_matches = [pattern.search("deplanbook-cms-canary") for pattern in patterns]

    verify(not uncovered)
    verify(not any(autopar_matches))
    verify(not any(canary_matches))


@pytest.mark.asyncio
async def test_every_inventory_domain_enters_http_and_browser_check_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify every inventory domain enters http and browser check pipeline."""
    config = production_config()
    domain_entries = domain_configs(config)
    specs = [load_domain_spec(entry) for entry in domain_entries]
    http_checked: list[str] = []
    browser_checked: list[str] = []

    async def fake_http(
        spec: DomainCheckSpec, client: httpx.AsyncClient,
    ) -> tuple[bool, JsonObject]:
        _ = client
        await asyncio.sleep(0)
        http_checked.append(spec.domain)
        return True, {"status_code": HTTPStatus.OK}

    async def fake_browser(
        spec: DomainCheckSpec, browser: Browser,
    ) -> tuple[bool, JsonObject]:
        _ = browser
        await asyncio.sleep(0)
        browser_checked.append(spec.domain)
        return True, {"http_status": HTTPStatus.OK}

    monkeypatch.setattr(monitoring, "http_get_check", fake_http)
    monkeypatch.setattr(monitoring, "browser_check", fake_browser)
    semaphore = asyncio.Semaphore(4)
    browser = cast("Browser", object())
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *(
                check_one_domain(spec, client, browser, browser_semaphore=semaphore)
                for spec in specs
            ),
        )

    verify({result.domain for result in results} == EXPECTED_ACTIVE_DOMAINS)
    verify(set(http_checked) == EXPECTED_ACTIVE_DOMAINS)
    browser_specs = [spec for spec in specs if spec.browser_enabled]
    expected_browser_domains = {spec.domain for spec in browser_specs}
    result_states = [result.ok for result in results]
    verify(set(browser_checked) == expected_browser_domains)
    verify(all(result_states))
