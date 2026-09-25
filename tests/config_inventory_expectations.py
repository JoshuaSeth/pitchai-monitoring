# Copyright (c) 2026 PitchAI. All rights reserved.
"""Authoritative inventory expectations shared by monitoring tests."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from domain_checks.main import load_config

if TYPE_CHECKING:
    from domain_checks.types import JsonObject

EXPECTED_ACTIVE_DOMAIN_COUNT = 58
EXPECTED_DOMAIN_GROUP_COUNT = 14

EXPECTED_ACTIVE_DOMAINS = {
    "pitchai.net",
    "www.pitchai.net",
    "assets.pitchai.net",
    "auth.pitchai.net",
    "breakglass.pitchai.net",
    "chat.pitchai.net",
    "codex-cowork.pitchai.net",
    "codex-voice.pitchai.net",
    "codexusage.pitchai.net",
    "cursussen.pitchai.net",
    "dispatch.pitchai.net",
    "filedrop.pitchai.net",
    "monitoring.pitchai.net",
    "navigation.pitchai.net",
    "onboarding-course.pitchai.net",
    "orthoparse.pitchai.net",
    "privacy-gateway.pitchai.net",
    "route-anchor.pitchai.net",
    "storage.pitchai.net",
    "suggestions.pitchai.net",
    "tools.pitchai.net",
    "wiki.pitchai.net",
    "registry.pitchai.net",
    "afasask.pitchai.net",
    "auth.autopar.pitchai.net",
    "autopar.pitchai.net",
    "deplanbook.pitchai.net",
    "dpb.pitchai.net",
    "formatief-toetsen.pitchai.net",
    "potaito.pitchai.net",
    "skybuyfly.pitchai.net",
    "stable.skybuyfly.pitchai.net",
    "aigenda-rules.demos.pitchai.net",
    "apologetica-wagtail-staging.pitchai.net",
    "demo.afasask.pitchai.net",
    "dft-marketing-staging.pitchai.net",
    "digibeat.demos.pitchai.net",
    "privacy-gateway-staging.pitchai.net",
    "staging.afasask.pitchai.net",
    "staging.autopar.pitchai.net",
    "staging.chat.pitchai.net",
    "staging.formatief-toetsen.pitchai.net",
    "staging.hetcis.pitchai.net",
    "staging.potaito.pitchai.net",
    "studentenreisproduct.demos.pitchai.net",
    "jeff-codex-voice.pitchai.net",
    "jeff-dispatch.pitchai.net",
    "jeff-work-inbox.pitchai.net",
    "aardappelprijs.nl",
    "akkerbouwprijs.nl",
    "afasask.gzb.nl",
    "deplanbook.com",
    "cms.deplanbook.com",
    "hetcis.nl",
    "www.hetcis.nl",
    "agentcloud.pitchai.net",
    "dashboards.pitchai.net",
    "support.pitchai.net",
}

REQUIRED_RUNTIME_DEPENDENCIES = {
    "service-monitoring",
    "e2e-registry",
    "e2e-runner",
    "registry",
    "afasask",
    "afasask-demo",
    "afasask-quick-chat",
    "afasask-quick-chat-staging",
    "afas-sync",
    "pgbouncer-afasask",
    "pgbouncer-autopar",
    "pgbouncer-potaito",
    "autopar",
    "autopar-auth",
    "codex-cowork-webapp",
    "apologetica-wagtail-staging",
    "apologetica-wagtail-staging-db",
    "potaito-web-harvest",
    "potai-staging",
    "aipc-skybuyfly-primary",
    "aipc-skybuyfly-backup",
    "skybuyfly-quick-chat",
    "aipc-crawler",
    "aipc-match-dependent-ops",
    "aipc-product-image-refresher",
    "aipc-qdrant-sync",
    "aipc-search-derived-fields",
    "aipc-meilisync",
    "qdrant",
    "meilisearch",
    "pgbouncer-aipc",
    "deplanbook-play",
    "deplanbook-cms",
    "deplanbook-libretranslate",
    "deplanbook-db-proxy",
    "pgbouncer-deplanbook",
    "dft-web-app-green",
    "dft-web-app",
    "dft-web-app-staging",
    "dft-web-app-staging-spend-enabled",
    "staging-temp-web",
    "dft-worker-green",
    "dft-worker-staging",
    "dft-worker-staging-spend-enabled",
    "dft-batch-progress-redis",
    "dft-batch-progress-redis-main-candidate",
    "dft-batch-progress-redis-staging",
    "dft-batch-progress-redis-staging-spend-enabled",
    "dft-batch-progress-redis-staging-temp-bas",
    "dft-llm-mock-openai-staging",
    "meilisearch-formatief-toetsen",
    "meilisync-formatief-toetsen",
    "meilisync-formatief-toetsen-staging",
    "pgbouncer-dft",
    "pgbouncer-dft-staging",
    "orthoparse-web-app-green",
    "orthoparse-web-app",
    "orthoparse-ceph-worker",
    "orthoparse-worker-green",
    "pgbouncer-orthoparse",
    "pitchai-onboarding-course-onboarding-course-1",
    "pitchai-breakglass-web-terminal",
    "quickchat-rsr-demo",
}


def production_config() -> JsonObject:
    """Load the production monitoring config.

    Returns:
        The parsed monitoring config.
    """
    config_path = Path(__file__).resolve().parents[1] / "domain_checks" / "config.yaml"
    return load_config(config_path)


def domain_configs(config: JsonObject) -> list[JsonObject]:
    """Return the validated domain mappings from a monitoring config.

    Returns:
        The non-empty list of domain config mappings.
    """
    raw_domains = config.get("domains")
    if not isinstance(raw_domains, list) or not raw_domains:
        pytest.fail("config.yaml domains list is empty")
    domains: list[JsonObject] = []
    for raw_domain in raw_domains:
        if not isinstance(raw_domain, dict):
            pytest.fail(f"Expected domain mapping, got {raw_domain!r}")
        domains.append(raw_domain)
    return domains
