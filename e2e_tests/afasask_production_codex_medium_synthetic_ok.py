# Copyright (c) 2026 PitchAI. All rights reserved.
"""Trusted production AFASAsk Codex medium real-generation canary."""

from __future__ import annotations

import asyncio
import base64
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, Protocol
from urllib.parse import quote

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

_PRODUCTION_ORIGIN = "https://afasask.gzb.nl"
_SUCCESS_MARKER = "afasask_production_medium_canary_ok"
_ROW_COUNT = re.compile(r"31[.,]?465")
_FAILURE_MARKERS = (
    "afasask_production_medium_canary_fail",
    "geen tool-calls",
    "please log out",
    "auth invalid",
    "auth failure",
    "refresh_token",
    "http 429",
    "hit your usage limit",
    "usage_limit_reached",
)


class _CanaryError(RuntimeError):
    """Expected canary contract failure."""


class _Response(NamedTuple):
    status: int


class _LoginRequest(Protocol):
    async def __call__(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        max_redirects: int,
    ) -> _Response:
        """Issue one session-preserving login request."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the adapter contract name."""
        raise NotImplementedError

    def supports_headers(self) -> bool:
        """Report support for explicit request headers."""
        raise NotImplementedError


class _RequestOperations(NamedTuple):
    get: _LoginRequest


class _ContextOperations(NamedTuple):
    request: _RequestOperations


@dataclass(frozen=True)
class _LocatorOperations:
    last: _LocatorOperations
    click: Callable[[], Awaitable[None]]
    count: Callable[[], Awaitable[int]]
    fill: Callable[[str], Awaitable[None]]
    inner_text: Callable[[], Awaitable[str]]
    input_value: Callable[[], Awaitable[str]]


class _PageOperations(NamedTuple):
    context: _ContextOperations
    url: str
    get_by_test_id: Callable[[str], _LocatorOperations]
    locator: Callable[[str], _LocatorOperations]
    goto: Callable[[str], Awaitable[None]]
    set_default_timeout: Callable[[float], None]
    wait_for_function: Callable[[str, dict[str, int | list[str]]], Awaitable[None]]
    wait_for_selector: Callable[[str], Awaitable[None]]


def _require(*, passed: bool, message: str) -> None:
    if not passed:
        raise _CanaryError(message)


def _credentials() -> tuple[str, str]:
    username = (os.getenv("AFASASK_DEMO_USERNAME") or "").strip()
    password = os.getenv("AFASASK_DEMO_PASSWORD") or ""
    _require(passed=bool(username), message="missing AFASASK_DEMO_USERNAME")
    _require(passed=bool(password), message="missing AFASASK_DEMO_PASSWORD")
    return username, password


async def _authenticate(
    page: _PageOperations,
    origin: str,
    path: str,
    username: str,
    password: str,
) -> None:
    basic_token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    login_url = origin + f"/login-admin?next={quote(path, safe='')}"
    login_response = await page.context.request.get(
        login_url,
        headers={"Authorization": f"Basic {basic_token}"},
        max_redirects=0,
    )
    _require(
        passed=login_response.status in {302, 307},
        message=f"trusted_login_failed: status={login_response.status}",
    )
    await page.goto(origin + path)
    _require(passed="/login-page" not in page.url, message="trusted_login_session_not_applied")
    await page.wait_for_selector("[data-testid='chat-input']")
    await page.wait_for_selector("[data-testid='codex-intensity-selector']")


def _write_artifact(directory: str, content: str) -> None:
    artifacts = Path(directory)
    artifacts.mkdir(parents=True, exist_ok=True)
    artifact = artifacts / "afasask_production_codex_medium_synthetic_ok.txt"
    artifact.write_text(content, encoding="utf-8")


async def run(page: _PageOperations, base_url: str, artifacts_dir: str) -> None:
    """Run one authenticated, read-only Codex medium generation check."""
    origin = base_url.rstrip("/")
    _require(passed=origin == _PRODUCTION_ORIGIN, message=f"unexpected_production_origin: {origin}")
    page.set_default_timeout(240_000)
    path = (
        f"/chat/demo/afasask-production-monitor-codex-medium-{uuid.uuid4().hex[:12]}"
        "?floating=false&reload=true&mode=codex&intensity=medium"
    )
    await _authenticate(page, origin, path, *_credentials())

    await page.get_by_test_id("codex-intensity-medium").click()
    intensity = await page.locator("#codex-intensity").input_value()
    _require(passed=intensity == "medium", message=f"wrong_intensity: {intensity!r}")

    prompt = (
        "AFASASK_PRODUCTION_MEDIUM_MONITORING_CANARY. This is an internal read-only health check. "
        "Use Python to open parquet/Sales_SalesOrderHeader.csv and calculate its exact row count. "
        f"Do not include personal data. Reply with {_SUCCESS_MARKER.upper()} and the row count."
    )
    assistant_count = await page.locator('article[data-role="assistant"]').count()
    await page.get_by_test_id("chat-input").fill(prompt)
    started = time.monotonic()
    await page.get_by_test_id("chat-submit").click()
    await page.wait_for_function(
        """(state) => {
          const articles = Array.from(document.querySelectorAll('article[data-role="assistant"]'));
          if (articles.length <= state.assistantCount) return false;
          const text = articles.length ? (articles[articles.length - 1].textContent || '') : '';
          const lower = text.toLowerCase();
          return (lower.includes('klaar')
              && lower.includes('afasask_production_medium_canary_ok')
              && /31[.,]?465/.test(text))
            || state.failureMarkers.some((marker) => lower.includes(marker));
        }""",
        {"assistantCount": assistant_count, "failureMarkers": list(_FAILURE_MARKERS)},
    )

    response = await page.locator('article[data-role="assistant"]').last.inner_text()
    lowered = response.lower()
    failure_marker = next((marker for marker in _FAILURE_MARKERS if marker in lowered), None)
    _require(passed=failure_marker is None, message=f"medium_canary_failure_marker: {failure_marker}")
    _require(passed=_SUCCESS_MARKER in lowered, message=f"medium_canary_wrong_response: {response[:500]!r}")
    _require(
        passed=_ROW_COUNT.search(response) is not None,
        message=f"medium_canary_wrong_row_count: {response[:500]!r}",
    )

    await asyncio.to_thread(
        _write_artifact,
        artifacts_dir,
        f"url={page.url}\nelapsed_seconds={time.monotonic() - started:.1f}\nresponse={response[:1000]}\n",
    )
