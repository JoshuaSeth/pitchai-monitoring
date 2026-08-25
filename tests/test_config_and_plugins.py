from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

import domain_checks.main as monitoring
from domain_checks.inventory import validate_domain_inventory
from domain_checks.main import (
    _normalize_domain_entries,
    _route_domain_telegram_alert,
    check_one_domain,
    load_config,
    load_domain_spec,
)
from domain_checks.telegram import TelegramConfig


EXPECTED_ACTIVE_DOMAINS = set(
    """
    pitchai.net
    www.pitchai.net
    assets.pitchai.net
    auth.pitchai.net
    breakglass.pitchai.net
    chat.pitchai.net
    codex-cowork.pitchai.net
    codex-voice.pitchai.net
    codexusage.pitchai.net
    cursussen.pitchai.net
    dispatch.pitchai.net
    filedrop.pitchai.net
    monitoring.pitchai.net
    navigation.pitchai.net
    onboarding-course.pitchai.net
    orthoparse.pitchai.net
    privacy-gateway.pitchai.net
    route-anchor.pitchai.net
    storage.pitchai.net
    suggestions.pitchai.net
    tools.pitchai.net
    wiki.pitchai.net
    registry.pitchai.net
    afasask.pitchai.net
    auth.autopar.pitchai.net
    autopar.pitchai.net
    deplanbook.pitchai.net
    dpb.pitchai.net
    formatief-toetsen.pitchai.net
    potaito.pitchai.net
    skybuyfly.pitchai.net
    stable.skybuyfly.pitchai.net
    aigenda-rules.demos.pitchai.net
    apologetica-wagtail-staging.pitchai.net
    demo.afasask.pitchai.net
    dft-marketing-staging.pitchai.net
    digibeat.demos.pitchai.net
    privacy-gateway-staging.pitchai.net
    staging.afasask.pitchai.net
    staging.autopar.pitchai.net
    staging.chat.pitchai.net
    staging.formatief-toetsen.pitchai.net
    staging.hetcis.pitchai.net
    staging.potaito.pitchai.net
    studentenreisproduct.demos.pitchai.net
    jeff-codex-voice.pitchai.net
    jeff-dispatch.pitchai.net
    jeff-work-inbox.pitchai.net
    aardappelprijs.nl
    akkerbouwprijs.nl
    afasask.gzb.nl
    deplanbook.com
    cms.deplanbook.com
    hetcis.nl
    www.hetcis.nl
    agentcloud.pitchai.net
    dashboards.pitchai.net
    support.pitchai.net
    """.split()
)

EXPECTED_DASHBOARD_ONLY_DOMAINS = {
    "registry.pitchai.net",
    "agentcloud.pitchai.net",
    "dashboards.pitchai.net",
    "support.pitchai.net",
    "cursussen.pitchai.net",
}


def _production_config() -> dict:
    config_path = Path(__file__).resolve().parents[1] / "domain_checks" / "config.yaml"
    return load_config(config_path)


def test_all_config_domains_have_check_specs() -> None:
    config = _production_config()
    validate_domain_inventory(config)
    domains = config.get("domains")
    assert isinstance(domains, list)
    assert domains, "config.yaml domains list is empty"

    specs = [load_domain_spec(entry) for entry in domains]
    assert len(specs) == len(domains)

    for spec in specs:
        assert spec.domain
        assert spec.url.startswith(("http://", "https://"))
        has_any_assertion = bool(
            spec.required_selectors_all
            or spec.required_selectors_any
            or spec.required_text_all
            or spec.expected_title_contains
        )
        assert has_any_assertion, f"{spec.domain} has no browser assertions"


def test_authoritative_active_inventory_is_exact_and_dft_is_enabled() -> None:
    config = _production_config()
    domains = config["domains"]
    actual = {str(entry["domain"]) for entry in domains}

    assert actual == EXPECTED_ACTIVE_DOMAINS
    assert len(domains) == len(actual) == 58
    assert len(config["domain_groups"]) == 14
    assert not [entry for entry in domains if entry.get("disabled") or entry.get("enabled") is False]

    dft = {entry["domain"]: load_domain_spec(entry) for entry in domains if entry["group"] == "dft"}
    assert set(dft) == {
        "formatief-toetsen.pitchai.net",
        "staging.formatief-toetsen.pitchai.net",
        "dft-marketing-staging.pitchai.net",
    }
    assert dft["formatief-toetsen.pitchai.net"].url.endswith("/healthz")
    assert dft["staging.formatief-toetsen.pitchai.net"].url.endswith("/healthz")


def test_alert_policy_has_only_the_five_explicit_dashboard_only_domains() -> None:
    config = _production_config()
    entries = _normalize_domain_entries(config["domains"])
    entries_by_domain = {entry.domain: entry for entry in entries}

    assert {entry.domain for entry in entries if not entry.routes_telegram} == (
        EXPECTED_DASHBOARD_ONLY_DOMAINS
    )
    assert all(
        entry.alert_policy.reason
        for entry in entries
        if entry.domain in EXPECTED_DASHBOARD_ONLY_DOMAINS
    )
    assert entries_by_domain["pitchai.net"].routes_telegram is True
    assert entries_by_domain["dispatch.pitchai.net"].routes_telegram is True
    assert entries_by_domain["aardappelprijs.nl"].routes_telegram is True

    inventory_by_domain = {str(entry["domain"]): entry for entry in config["domains"]}
    assert inventory_by_domain["aardappelprijs.nl"]["group"] == "potaito"


@pytest.mark.asyncio
async def test_domain_telegram_router_suppresses_dashboard_only_and_routes_critical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = {
        entry.domain: entry for entry in _normalize_domain_entries(_production_config()["domains"])
    }
    sent: list[str] = []

    async def fake_send(_client, _telegram_cfg, message: str):
        sent.append(message)
        return True, [{"ok": True}]

    monkeypatch.setattr(monitoring, "send_telegram_message_chunked", fake_send)
    telegram_cfg = TelegramConfig(bot_token="test-token", chat_id="test-chat")

    for domain in sorted(EXPECTED_DASHBOARD_ONLY_DOMAINS):
        routed = await _route_domain_telegram_alert(
            http_client=object(),
            telegram_cfg=telegram_cfg,
            entry=entries[domain],
            message=f"down: {domain}",
        )
        assert routed is None

    assert sent == []

    routed = await _route_domain_telegram_alert(
        http_client=object(),
        telegram_cfg=telegram_cfg,
        entry=entries["pitchai.net"],
        message="down: pitchai.net",
    )
    assert routed == (True, [{"ok": True}])
    assert sent == ["down: pitchai.net"]


def test_container_health_patterns_cover_every_socket_visible_runtime_dependency() -> None:
    required = {
        "service-monitoring", "e2e-registry", "e2e-runner", "registry",
        "afasask", "afasask-demo", "afasask-quick-chat", "afasask-quick-chat-staging",
        "afas-sync", "pgbouncer-afasask", "pgbouncer-autopar", "pgbouncer-potaito",
        "autopar", "autopar-auth", "codex-cowork-webapp",
        "apologetica-wagtail-staging", "apologetica-wagtail-staging-db",
        "potaito-web-harvest", "potai-staging",
        "aipc-skybuyfly-primary", "aipc-skybuyfly-backup", "skybuyfly-quick-chat",
        "aipc-crawler", "aipc-match-dependent-ops", "aipc-product-image-refresher",
        "aipc-qdrant-sync", "aipc-search-derived-fields", "aipc-meilisync",
        "qdrant", "meilisearch", "pgbouncer-aipc",
        "deplanbook-play", "deplanbook-cms", "deplanbook-libretranslate",
        "deplanbook-db-proxy", "pgbouncer-deplanbook",
        "dft-web-app-green", "dft-web-app", "dft-web-app-staging",
        "dft-web-app-staging-spend-enabled", "staging-temp-web",
        "dft-worker-green", "dft-worker-staging", "dft-worker-staging-spend-enabled",
        "dft-batch-progress-redis", "dft-batch-progress-redis-main-candidate",
        "dft-batch-progress-redis-staging", "dft-batch-progress-redis-staging-spend-enabled",
        "dft-batch-progress-redis-staging-temp-bas", "dft-llm-mock-openai-staging",
        "meilisearch-formatief-toetsen", "meilisync-formatief-toetsen",
        "meilisync-formatief-toetsen-staging", "pgbouncer-dft", "pgbouncer-dft-staging",
        "orthoparse-web-app-green", "orthoparse-web-app", "orthoparse-ceph-worker",
        "orthoparse-worker-green", "pgbouncer-orthoparse",
        "pitchai-onboarding-course-onboarding-course-1", "pitchai-breakglass-web-terminal",
        "quickchat-rsr-demo",
    }
    patterns = [re.compile(pattern) for pattern in _production_config()["container_health"]["include_name_patterns"]]
    uncovered = sorted(name for name in required if not any(pattern.search(name) for pattern in patterns))

    assert uncovered == []
    assert not any(pattern.search("autopar-batch-20260824") for pattern in patterns)
    assert not any(pattern.search("deplanbook-cms-canary") for pattern in patterns)


@pytest.mark.asyncio
async def test_every_inventory_domain_enters_http_and_browser_check_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _production_config()
    specs = [load_domain_spec(entry) for entry in config["domains"]]
    http_checked: list[str] = []
    browser_checked: list[str] = []

    async def fake_http(spec, _client):
        http_checked.append(spec.domain)
        return True, {"status_code": 200}

    async def fake_browser(spec, _browser):
        browser_checked.append(spec.domain)
        return True, {"http_status": 200}

    monkeypatch.setattr(monitoring, "http_get_check", fake_http)
    monkeypatch.setattr(monitoring, "browser_check", fake_browser)
    semaphore = asyncio.Semaphore(4)
    results = await asyncio.gather(
        *(check_one_domain(spec, object(), object(), browser_semaphore=semaphore) for spec in specs)
    )

    assert {result.domain for result in results} == EXPECTED_ACTIVE_DOMAINS
    assert set(http_checked) == EXPECTED_ACTIVE_DOMAINS
    assert set(browser_checked) == {spec.domain for spec in specs if spec.browser_enabled}
    assert all(result.ok for result in results)


def test_afasask_domains_are_enabled_and_check_current_user_surfaces() -> None:
    config = _production_config()
    domains = config.get("domains")
    assert isinstance(domains, list)

    entry = next((d for d in domains if isinstance(d, dict) and d.get("domain") == "afasask.gzb.nl"), None)
    assert entry is not None
    assert entry.get("disabled") is not True

    spec = load_domain_spec(entry)
    assert "mode=codex" in spec.url
    assert "intensity=medium" in spec.url
    assert any(item.selector == "#chat-input" for item in spec.required_selectors_all)
    assert any(item.selector == ".chat-submit" for item in spec.required_selectors_all)
    assert "Mislukt" not in spec.forbidden_text_any

    demo_entry = next(
        (d for d in domains if isinstance(d, dict) and d.get("domain") == "demo.afasask.pitchai.net"),
        None,
    )
    assert demo_entry is not None
    assert demo_entry.get("disabled") is not True

    demo_spec = load_domain_spec(demo_entry)
    assert "mode=codex" in demo_spec.url
    assert "intensity=fast" in demo_spec.url
    assert any(item.selector == "#main" for item in demo_spec.required_selectors_all)
    assert any(item.selector == "text=/Login with AFAS/i" for item in demo_spec.required_selectors_all)
    assert any(check.get("name") == "codex_no_quota_readiness" for check in demo_spec.api_contract_checks)

    readiness_checks = [
        next(check for check in item.api_contract_checks if check.get("name") == "codex_no_quota_readiness")
        for item in (spec, demo_spec)
    ]
    assert [check.get("coordination_key") for check in readiness_checks] == [
        "afasask_auth_broker_readiness",
        "afasask_auth_broker_readiness",
    ]
    assert all(
        "coordination_key" not in check
        for item in (spec, demo_spec)
        for check in item.api_contract_checks
        if check.get("name") != "codex_no_quota_readiness"
    )
