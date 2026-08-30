# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed production inventory fixtures for monitoring tests."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .domain_runtime import load_config
from .json_types import json_object, object_list, text_value

if TYPE_CHECKING:
    from .json_types import JsonInput, JsonObject

CONFIG_PATH = Path(__file__).resolve().parents[1] / "domain_checks" / "config.yaml"


def _words(value: str) -> frozenset[str]:
    return frozenset(re.findall(r"\S+", value))


EXPECTED_ACTIVE_DOMAINS = _words(
    """
    pitchai.net www.pitchai.net assets.pitchai.net auth.pitchai.net 2fa-server.37.27.67.52.nip.io
    breakglass.pitchai.net chat.pitchai.net codex-cowork.pitchai.net codex-voice.pitchai.net
    codexusage.pitchai.net cursussen.pitchai.net dispatch.pitchai.net filedrop.pitchai.net monitoring.pitchai.net
    navigation.pitchai.net onboarding-course.pitchai.net orthoparse.pitchai.net privacy-gateway.pitchai.net
    route-anchor.pitchai.net storage.pitchai.net suggestions.pitchai.net tools.pitchai.net wiki.pitchai.net
    whatsapp.pitchai.net registry.pitchai.net afasask.pitchai.net auth.autopar.pitchai.net autopar.pitchai.net
    deplanbook.pitchai.net dpb.pitchai.net formatief-toetsen.pitchai.net potaito.pitchai.net skybuyfly.pitchai.net
    stable.skybuyfly.pitchai.net aigenda-rules.demos.pitchai.net apologetica-wagtail-staging.pitchai.net
    demo.afasask.pitchai.net dft-marketing-staging.pitchai.net digibeat.demos.pitchai.net
    formatiefleren.nl www.formatiefleren.nl
    privacy-gateway-staging.pitchai.net staging.afasask.pitchai.net staging.autopar.pitchai.net
    staging.chat.pitchai.net staging.formatief-toetsen.pitchai.net staging.hetcis.pitchai.net
    staging.potaito.pitchai.net studentenreisproduct.demos.pitchai.net jeff-codex-voice.pitchai.net
    jeff-dispatch.pitchai.net jeff-work-inbox.pitchai.net aardappelprijs.nl akkerbouwprijs.nl afasask.gzb.nl
    deplanbook.com cms.deplanbook.com hetcis.nl www.hetcis.nl agentcloud.pitchai.net dashboards.pitchai.net
    support.pitchai.net
    aigenda.pitchai.net aigenda-monitor.pitchai.net livedocuments.pitchai.net lfs.pitchai.net
    servers.pitchai.net theplanbook.pitchai.net autopar-staging-web.37.27.67.52.nip.io
    unimixbrasil.com.br www.unimixbrasil.com.br
    """,
)

EXPECTED_DASHBOARD_ONLY_DOMAINS = frozenset({
    "registry.pitchai.net",
    "agentcloud.pitchai.net",
    "dashboards.pitchai.net",
    "support.pitchai.net",
    "cursussen.pitchai.net",
    "theplanbook.pitchai.net",
})

EXPECTED_RETIRED_DOMAINS = _words(
    """
    n8n.pitchai.net quickchat.pitchai.net digibead.demos.pitchai.net
    apologetica-react-staging.pitchai.net chat-staging.pitchai.net cowork.pitchai.net
    www.afasask.pitchai.net www.demo.afasask.pitchai.net jeff.codex-voice.pitchai.net
    jeff.dispatch.pitchai.net jeff.work-inbox.pitchai.net autodiscover.pitchai.net demos.pitchai.net
    www.afasask.gzb.nl app.doorstroomtoets.nl app-staging-no-spend.doorstroomtoets.nl
    cms.hetcis.nl weblog.hetcis.nl hetcis.pitchai.net staging.dispatch.pitchai.net
    aigenda.37.27.67.52.nip.io aigenda-rules.135-181-182-48.sslip.io
    driestar-aigenda.demos.pitchai.net theplanbook.com www.theplanbook.com staging.afasask.gzb.nl
    staging.hetcis.nl suggestions.demos.pitchai.net staging.potai.pitchai.net
    staging.potato.pitchai.net studentenreisproduct.nl www.centrumvoorisraelstudies.nl
    www.intern.centrumvoorisraelstudies.nl events.pitchai.net mockopenai.pitchai.net
    aipc.skybuyfly.com unimixbr.netlify.app
    """,
)

REQUIRED_CONTAINER_NAMES = _words(
    """
    service-monitoring database-dependency-monitor e2e-registry e2e-runner registry afasask afasask-demo
    afasask-quick-chat afasask-quick-chat-staging afas-sync pgbouncer-afasask pgbouncer-autopar
    pgbouncer-potaito autopar autopar-auth codex-cowork-webapp apologetica-wagtail-staging
    apologetica-wagtail-staging-db potaito-web-harvest potai-staging aipc-skybuyfly-primary
    aipc-skybuyfly-backup skybuyfly-quick-chat aipc-crawler aipc-match-dependent-ops
    aipc-product-image-refresher aipc-qdrant-sync aipc-search-derived-fields aipc-meilisync qdrant
    meilisearch pgbouncer-aipc deplanbook-play deplanbook-play-blue deplanbook-play-green deplanbook-cms
    deplanbook-libretranslate deplanbook-db-proxy pgbouncer-deplanbook twofa-server-prod dft-web-app
    dft-web-app-green dft-web-app-staging dft-web-app-staging-spend-enabled staging-temp-web dft-worker
    dft-worker-green dft-worker-staging dft-worker-staging-spend-enabled dft-batch-progress-redis
    dft-batch-progress-redis-main-candidate dft-batch-progress-redis-staging
    dft-batch-progress-redis-staging-spend-enabled dft-batch-progress-redis-staging-temp-bas
    dft-llm-mock-openai-staging meilisearch-formatief-toetsen meilisync-formatief-toetsen
    meilisync-formatief-toetsen-staging pgbouncer-dft pgbouncer-dft-staging orthoparse-web-app
    orthoparse-web-app-green orthoparse-ceph-worker orthoparse-worker orthoparse-worker-green
    pgbouncer-orthoparse pitchai-onboarding-course-onboarding-course-1 pitchai-breakglass-web-terminal
    quickchat-rsr-demo aigenda-webapp aigenda-webapp-monitor autopar-staging-web autopar-staging-db
    """,
)


def production_config() -> JsonObject:
    """Return the canonical production config through the strict JSON boundary."""
    loaded = cast("JsonInput", load_config(CONFIG_PATH))
    return json_object(loaded)


def production_domains() -> list[JsonObject]:
    """Return every active production monitoring entry."""
    config = production_config()
    return object_list(config.get("domains"))


def entry_by_domain(domain: str) -> JsonObject:
    """Return one exact active domain entry or fail the test loudly.

    Raises:
        AssertionError: If the domain is absent from the active inventory.
    """
    entry = next(
        (item for item in production_domains() if text_value(item.get("domain")) == domain),
        None,
    )
    if entry is None:
        message = f"active monitoring domain is missing: {domain}"
        raise AssertionError(message)
    return entry
