from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

import domain_checks.main as monitoring
from domain_checks.inventory import validate_domain_inventory
from domain_checks.main import check_one_domain, load_config, load_domain_spec


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
    2fa-server.37.27.67.52.nip.io
    """.split()
)


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
    assert len(domains) == len(actual) == 59
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
        "quickchat-rsr-demo", "twofa-server-prod",
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
    assert any("login-admin" in item.selector for item in demo_spec.required_selectors_all)
    assert not any(item.selector == "#chat-input" for item in demo_spec.required_selectors_all)
    assert any(
        step.get("type") == "expect_url_contains" and step.get("value") == "/login-page"
        for transaction in demo_spec.synthetic_transactions
        for step in transaction.get("steps", [])
    )
    assert any(check.get("name") == "codex_no_quota_readiness" for check in demo_spec.api_contract_checks)


def test_afasask_demo_canary_fails_fast_on_explicit_data_failure() -> None:
    """Keep rendered canary failures out of the generic 240-second timeout path."""
    source_path = Path(__file__).resolve().parents[1] / "e2e_tests" / "afasask_demo_codex_fast_ok.py"
    source = source_path.read_text(encoding="utf-8")

    assert '"afasask_demo_canary_fail"' in source
    assert "state.failureMarkers.some" in source
    assert "for marker in _FAILURE_MARKERS" in source


def test_autopar_contract_models_the_protected_login_boundary() -> None:
    config_path = Path(__file__).resolve().parents[1] / "domain_checks" / "config.yaml"
    config = load_config(config_path)
    domains = config.get("domains")
    assert isinstance(domains, list)

    entry = next(
        (item for item in domains if isinstance(item, dict) and item.get("domain") == "autopar.pitchai.net"),
        None,
    )
    assert entry is not None

    spec = load_domain_spec(entry)
    assert spec.url == "https://autopar.pitchai.net"
    assert spec.allowed_status_codes == [200]
    assert spec.expected_title_contains == "AutoPAR"
    assert spec.expected_final_host_suffix == "autopar.pitchai.net"
    assert spec.expected_final_path == "/login-page"
    assert [item.selector for item in spec.required_selectors_all] == [
        "form[action='/login-token'] input[name='token']"
    ]

    health = next(check for check in spec.api_contract_checks if check.get("name") == "health")
    assert health["path"] == "/health"
    assert health["expected_status_codes"] == [200]
    assert health["json_paths_equal"] == {"status": "healthy"}

    transaction = next(
        item for item in spec.synthetic_transactions if item.get("name") == "token_login_landing"
    )
    steps = transaction["steps"]
    assert {"type": "expect_url_contains", "value": "/login-page"} in steps
    assert {"type": "expect_title_contains", "value": "AutoPAR"} in steps
    assert all("script#wss-connection" not in str(step) for step in steps)
