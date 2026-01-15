from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
from playwright.async_api import async_playwright

from domain_checks.common_check import find_chromium_executable
from domain_checks.main import check_one_domain, load_config, load_domain_spec


pytestmark = pytest.mark.live


if os.getenv("RUN_LIVE_TESTS") != "1":
    pytest.skip("Set RUN_LIVE_TESTS=1 to run live domain checks", allow_module_level=True)


EXPECTED_UP = {
    "afasask.pitchai.net",
    "autopar.pitchai.net",
    "skybuyfly.pitchai.net",
}


@pytest.mark.asyncio
async def test_expected_up_domains_are_up() -> None:
    config_path = Path(__file__).resolve().parents[1] / "domain_checks" / "config.yaml"
    config = load_config(config_path)
    domains = config.get("domains") or []

    specs = []
    for entry in domains:
        spec = load_domain_spec(entry)
        if spec.domain in EXPECTED_UP:
            specs.append(spec)

    assert specs, "No live specs selected"

    chromium_path = find_chromium_executable()
    if not chromium_path:
        pytest.skip("No chromium/chrome available for Playwright")

    async with httpx.AsyncClient(headers={"User-Agent": "PitchAI Service Monitoring Bot"}) as http_client:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                executable_path=chromium_path,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                results = [await check_one_domain(spec, http_client, browser) for spec in specs]
            finally:
                await browser.close()

    failures = [r for r in results if not r.ok]
    assert not failures, f"Live domain check failures: {failures!r}"
