# Copyright (c) 2026 PitchAI. All rights reserved.
"""Half-hourly AFASAsk demo Codex real-generation monitoring canary."""

from __future__ import annotations

import asyncio
import base64
import os
import re
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    from playwright.async_api import Page

_FAILURE_MARKERS = (
    "afasask_demo_canary_fail",
    "❌ mislukt",
    "codex-modus",
    "usage_limit_reached",
    "hit your usage limit",
    "http 429",
    "refresh_token",
    "auth failure",
    "auth invalid",
    "please log out",
    "backend",
    "geen tool-calls",
)


def _require(message: str, *, condition: bool) -> None:
    if not condition:
        raise RuntimeError(message)


def _write_artifact(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


async def _authenticate_demo(page: Page, *, base_url: str, path: str) -> None:
    username = (os.getenv("AFASASK_DEMO_USERNAME") or "").strip()
    password = os.getenv("AFASASK_DEMO_PASSWORD") or ""
    _require("missing AFASASK_DEMO_USERNAME", condition=bool(username))
    _require("missing AFASASK_DEMO_PASSWORD", condition=bool(password))
    basic_token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    login_url = base_url.rstrip("/") + f"/login-admin?next={quote(path, safe='')}"
    login_response = await page.context.request.get(
        login_url,
        headers={"Authorization": f"Basic {basic_token}"},
        max_redirects=0,
    )
    _require(
        f"demo_login_failed: status={login_response.status}",
        condition=login_response.status in {302, 307},
    )
    await page.goto(base_url.rstrip("/") + path, wait_until="domcontentloaded")
    _require("demo_login_session_not_applied", condition="/login-page" not in page.url)


def _verify_assistant_response(assistant_text: str) -> None:
    lower = assistant_text.lower()
    for marker in _FAILURE_MARKERS:
        _require(
            f"afasask_demo_codex_canary_failed_marker: {marker}",
            condition=marker not in lower,
        )
    _require(
        f"afasask_demo_codex_canary_wrong_response: {assistant_text[:500]!r}",
        condition="afasask_demo_canary_ok" in lower,
    )
    _require(
        f"afasask_demo_codex_canary_wrong_row_count: {assistant_text[:500]!r}",
        condition=re.search(r"31[.,]?465", assistant_text) is not None,
    )


async def run(page: Page, base_url: str, artifacts_dir: str | Path) -> None:
    """Exercise the authenticated Codex-fast demo flow and record evidence."""
    conversation_id = f"afasask-demo-monitor-codex-fast-ok-{uuid.uuid4().hex[:12]}"
    path = f"/chat/demo/{conversation_id}?floating=false&reload=true&mode=codex&intensity=fast"
    await _authenticate_demo(page, base_url=base_url, path=path)
    await page.wait_for_selector("[data-testid='chat-input']", timeout=30_000)
    await page.wait_for_selector("[data-testid='codex-intensity-selector']", timeout=30_000)

    await page.get_by_test_id("codex-intensity-fast").click()
    hidden_intensity = await page.locator("#codex-intensity").input_value(timeout=10_000)
    _require(f"wrong_intensity: {hidden_intensity!r}", condition=hidden_intensity == "fast")

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
        """(state) => {
          const articles = Array.from(document.querySelectorAll('article[data-role="assistant"]'));
          if (articles.length <= state.assistantCountBefore) return false;
          const text = articles.length ? (articles[articles.length - 1].textContent || '') : '';
          const lower = text.toLowerCase();
          return (lower.includes('klaar')
              && lower.includes('afasask_demo_canary_ok')
              && /31[.,]?465/.test(text))
            || state.failureMarkers.some((marker) => lower.includes(marker));
        }""",
        arg={
            "assistantCountBefore": assistant_count_before,
            "failureMarkers": list(_FAILURE_MARKERS),
        },
        timeout=240_000,
    )

    assistant_text = await page.locator('article[data-role="assistant"]').last.inner_text(timeout=10_000)
    _verify_assistant_response(assistant_text)

    artifact_path = Path(artifacts_dir) / "afasask_demo_codex_fast_ok.txt"
    await asyncio.to_thread(
        _write_artifact,
        artifact_path,
        f"url={page.url}\nelapsed_seconds={time.time() - started:.1f}\nresponse={assistant_text[:1000]}\n",
    )
