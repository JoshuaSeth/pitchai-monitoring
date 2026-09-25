# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tests for test live domains behavior."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

from domain_checks.main import (
    check_one_domain,
    load_config,
    load_domain_spec,
    normalize_domain_entries,
)
from domain_checks.testing import verify
from tests.local_server_support import launched_browser

if TYPE_CHECKING:
    from domain_checks.common_check import DomainCheckSpec

pytestmark = pytest.mark.live


if os.getenv("RUN_LIVE_TESTS") != "1":
    pytest.skip(
        "Set RUN_LIVE_TESTS=1 to run live domain checks", allow_module_level=True,
    )


EXPECTED_UP = {
    "afasask.pitchai.net",
    "afasask.gzb.nl",
    "autopar.pitchai.net",
    "cms.deplanbook.com",
    "codexusage.pitchai.net",
    "deplanbook.com",
    "demo.afasask.pitchai.net",
    "dpb.pitchai.net",
    "hetcis.nl",
    "www.hetcis.nl",
    "skybuyfly.pitchai.net",
    "formatief-toetsen.pitchai.net",
    "staging.formatief-toetsen.pitchai.net",
}
CONFIG_PATH = Path(__file__).resolve().parents[1] / "domain_checks" / "config.yaml"


@pytest.mark.asyncio
async def test_expected_up_domains_are_up() -> None:
    """Verify expected up domains are up."""
    config = load_config(CONFIG_PATH)
    domains = config.get("domains") or []
    if not isinstance(domains, list):
        pytest.fail("domain_checks/config.yaml domains must be a list")

    specs: list[DomainCheckSpec] = []
    now_ts = time.time()
    for entry in normalize_domain_entries(domains):
        # Keep the live test aligned with production: don't assert on domains
        # explicitly disabled in config.
        if entry.is_disabled(now_ts):
            continue
        spec = load_domain_spec(entry.raw_entry)
        if spec.domain in EXPECTED_UP:
            specs.append(spec)

    verify(specs, "No live specs selected")

    async with (
        httpx.AsyncClient(
            headers={"User-Agent": "PitchAI Service Monitoring Bot"},
        ) as http_client,
        launched_browser() as browser,
    ):
        sem = asyncio.Semaphore(1)
        results = [
            await check_one_domain(spec, http_client, browser, browser_semaphore=sem)
            for spec in specs
        ]

    failures = [r for r in results if not r.ok]
    verify(not failures, f"Live domain check failures: {failures!r}")
