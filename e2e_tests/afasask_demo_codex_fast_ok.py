"""Half-hourly AFASAsk demo Codex real-generation monitoring canary."""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path


async def run(page, base_url, artifacts_dir):
    conversation_id = f"afasask-demo-monitor-codex-fast-ok-{uuid.uuid4().hex[:12]}"
    url = (
        base_url.rstrip("/")
        + f"/chat/demo/{conversation_id}?floating=false&reload=true&mode=codex&intensity=fast"
    )
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_selector("[data-testid='chat-input']", timeout=30_000)
    await page.wait_for_selector("[data-testid='codex-intensity-selector']", timeout=30_000)

    await page.get_by_test_id("codex-intensity-fast").click()
    hidden_intensity = await page.locator("#codex-intensity").input_value(timeout=10_000)
    assert hidden_intensity == "fast", f"wrong_intensity: {hidden_intensity!r}"

    prompt = (
        "AFASASK_DEMO_MONITORING_CANARY. This is an internal read-only health check. "
        "Use Python to open parquet/Sales_SalesOrderHeader.csv and calculate its exact row count. "
        "Do not include personal data. Reply with AFASASK_DEMO_CANARY_OK and the row count."
    )
    assistant_count_before = await page.locator('article[data-role="assistant"]').count()
    await page.get_by_test_id("chat-input").fill(prompt)
    await page.get_by_test_id("chat-submit").click()

    started = time.time()
    await page.wait_for_function(
        """(assistantCountBefore) => {
          const articles = Array.from(document.querySelectorAll('article[data-role="assistant"]'));
          if (articles.length <= assistantCountBefore) return false;
          const text = articles.length ? (articles[articles.length - 1].textContent || '') : '';
          const lower = text.toLowerCase();
          return (lower.includes('klaar')
              && lower.includes('afasask_demo_canary_ok')
              && /31[.,]?465/.test(text))
            || lower.includes('❌ mislukt')
            || lower.includes('codex-modus')
            || lower.includes('usage_limit_reached')
            || lower.includes('hit your usage limit')
            || lower.includes('http 429')
            || lower.includes('refresh_token')
            || lower.includes('auth failure')
            || lower.includes('auth invalid')
            || lower.includes('backend')
            || lower.includes('geen tool-calls');
        }""",
        arg=assistant_count_before,
        timeout=240_000,
    )

    assistant_text = await page.locator('article[data-role="assistant"]').last.inner_text(timeout=10_000)
    lower = assistant_text.lower()
    failure_markers = [
        "❌ mislukt",
        "codex-modus te voltooien",
        "usage_limit_reached",
        "hit your usage limit",
        "http 429",
        "refresh_token",
        "please log out",
        "backend problem",
        "geen tool-calls",
    ]
    for marker in failure_markers:
        assert marker not in lower, f"afasask_demo_codex_canary_failed_marker: {marker}"
    assert "afasask_demo_canary_ok" in lower, (
        f"afasask_demo_codex_canary_wrong_response: {assistant_text[:500]!r}"
    )
    assert re.search(r"31[.,]?465", assistant_text), (
        f"afasask_demo_codex_canary_wrong_row_count: {assistant_text[:500]!r}"
    )

    artifacts = Path(artifacts_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "afasask_demo_codex_fast_ok.txt").write_text(
        f"url={page.url}\nelapsed_seconds={time.time() - started:.1f}\nresponse={assistant_text[:1000]}\n",
        encoding="utf-8",
    )
