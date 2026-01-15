from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path
from typing import Any

import httpx
from playwright.async_api import Browser, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError


DEFAULT_MAINTENANCE_TEXT = [
    "maintenance",
    "temporarily unavailable",
    "we'll be back",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
]

_SCRIPT_AND_STYLE_RE = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
_HTML_TAG_RE = re.compile(r"(?is)<[^>]+>")


@dataclass(frozen=True)
class SelectorCheck:
    selector: str
    state: str = "visible"  # playwright: 'attached'|'detached'|'visible'|'hidden'


@dataclass(frozen=True)
class DomainCheckSpec:
    domain: str
    url: str
    expected_title_contains: str | None = None
    required_selectors_all: list[SelectorCheck] = field(default_factory=list)
    required_selectors_any: list[SelectorCheck] = field(default_factory=list)
    required_text_all: list[str] = field(default_factory=list)
    forbidden_text_any: list[str] = field(default_factory=lambda: list(DEFAULT_MAINTENANCE_TEXT))
    http_timeout_seconds: float = 15.0
    browser_timeout_seconds: float = 25.0


@dataclass(frozen=True)
class DomainCheckResult:
    domain: str
    ok: bool
    reason: str
    details: dict[str, Any]


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _html_to_visible_text(html: str) -> str:
    without_scripts = _SCRIPT_AND_STYLE_RE.sub(" ", html)
    without_tags = _HTML_TAG_RE.sub(" ", without_scripts)
    return _normalize_text(without_tags)

def _safe_url(url: str) -> str:
    """
    Prevent huge/sensitive querystrings from bloating logs + dispatch prompts.
    """
    s = (url or "").strip()
    if not s:
        return s
    try:
        parts = urlsplit(s)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except Exception:
        return s[:500]


async def http_get_check(spec: DomainCheckSpec, client: httpx.AsyncClient) -> tuple[bool, dict[str, Any]]:
    try:
        resp = await client.get(spec.url, follow_redirects=True, timeout=spec.http_timeout_seconds)
    except httpx.RequestError as e:
        return False, {"error": f"http_error: {type(e).__name__}: {e}"}

    body = resp.text or ""
    body_norm = _html_to_visible_text(body)

    forbidden_hits = [kw for kw in spec.forbidden_text_any if kw and kw.lower() in body_norm]

    ok = (200 <= resp.status_code < 400) and not forbidden_hits
    return ok, {
        "status_code": resp.status_code,
        "final_url": _safe_url(str(resp.url)),
        "forbidden_hits": forbidden_hits,
    }


def _default_selector_state(selector: str) -> str:
    sel = selector.lstrip()
    if sel.startswith(("meta", "script", "link", "title")):
        return "attached"
    return "visible"


def _compile_selector_list(items: list[Any]) -> list[SelectorCheck]:
    checks: list[SelectorCheck] = []
    for item in items:
        if isinstance(item, SelectorCheck):
            checks.append(item)
        elif isinstance(item, str):
            checks.append(SelectorCheck(selector=item, state=_default_selector_state(item)))
        elif isinstance(item, dict) and "selector" in item:
            selector = str(item["selector"])
            checks.append(
                SelectorCheck(
                    selector=selector,
                    state=str(item.get("state") or _default_selector_state(selector)),
                )
            )
        else:
            raise ValueError(f"Invalid selector check: {item!r}")
    return checks


def load_domain_spec_from_module_dict(module_vars: dict[str, Any]) -> DomainCheckSpec:
    if "CHECK" not in module_vars or not isinstance(module_vars["CHECK"], dict):
        raise ValueError("Domain check module must define a dict named CHECK")

    cfg = module_vars["CHECK"]
    required_all = _compile_selector_list(cfg.get("required_selectors_all", []))
    required_any = _compile_selector_list(cfg.get("required_selectors_any", []))

    forbidden = cfg.get("forbidden_text_any", None)
    if forbidden is None:
        forbidden = list(DEFAULT_MAINTENANCE_TEXT)

    return DomainCheckSpec(
        domain=str(cfg["domain"]),
        url=str(cfg["url"]),
        expected_title_contains=cfg.get("expected_title_contains"),
        required_selectors_all=required_all,
        required_selectors_any=required_any,
        required_text_all=[str(t) for t in cfg.get("required_text_all", [])],
        forbidden_text_any=[str(t) for t in forbidden],
        http_timeout_seconds=float(cfg.get("http_timeout_seconds", 15.0)),
        browser_timeout_seconds=float(cfg.get("browser_timeout_seconds", 25.0)),
    )


async def browser_check(spec: DomainCheckSpec, browser: Browser) -> tuple[bool, dict[str, Any]]:
    timeout_ms = int(spec.browser_timeout_seconds * 1000)

    context = await browser.new_context(viewport={"width": 1280, "height": 720})
    page = await context.new_page()
    try:
        try:
            response = await page.goto(spec.url, wait_until="domcontentloaded", timeout=timeout_ms)
        except PlaywrightError as e:
            return False, {"error": f"browser_goto_error: {type(e).__name__}: {e}"}

        status = response.status if response else None

        title = await page.title()
        title_ok = True
        if spec.expected_title_contains:
            title_ok = spec.expected_title_contains.lower() in (title or "").lower()

        body_text = _normalize_text(await page.evaluate("() => document.body?.innerText || ''"))
        forbidden_hits = [kw for kw in spec.forbidden_text_any if kw and kw.lower() in body_text]

        missing_all: list[str] = []
        for check in spec.required_selectors_all:
            try:
                await page.wait_for_selector(check.selector, state=check.state, timeout=timeout_ms)
            except PlaywrightTimeoutError:
                missing_all.append(check.selector)

        any_ok = True
        any_candidates = [c.selector for c in spec.required_selectors_any]
        if spec.required_selectors_any:
            any_ok = False
            tasks = [
                asyncio.create_task(
                    page.wait_for_selector(check.selector, state=check.state, timeout=timeout_ms)
                )
                for check in spec.required_selectors_any
            ]
            pending: set[asyncio.Task[Any]] = set(tasks)
            deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000.0)
            try:
                while pending and not any_ok:
                    remaining = max(0.0, deadline - asyncio.get_running_loop().time())
                    if remaining <= 0:
                        break
                    done, pending = await asyncio.wait(pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
                    if not done:
                        break
                    for task in done:
                        try:
                            await task
                        except PlaywrightTimeoutError:
                            continue
                        except Exception:
                            continue
                        else:
                            any_ok = True
                            break
            finally:
                for task in pending:
                    task.cancel()
                for task in pending:
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass

        missing_text: list[str] = []
        for t in spec.required_text_all:
            if _normalize_text(t) not in body_text:
                missing_text.append(t)

        ok = (
            (status is None or (200 <= status < 400))
            and title_ok
            and not forbidden_hits
            and not missing_all
            and any_ok
            and not missing_text
        )

        return ok, {
            "final_url": _safe_url(page.url),
            "http_status": status,
            "title": title,
            "title_ok": title_ok,
            "forbidden_hits": forbidden_hits,
            "missing_selectors_all": missing_all,
            "required_any_selectors": any_candidates,
            "required_any_ok": any_ok,
            "missing_text": missing_text,
        }
    finally:
        try:
            await page.close()
        finally:
            await context.close()


def find_chromium_executable() -> str | None:
    env_path = os.getenv("CHROMIUM_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    candidates = [
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return None
