from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from playwright.async_api import Browser, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

from domain_checks.common_check import _is_browser_infra_error  # noqa: SLF001


@dataclass(frozen=True)
class SyntheticTransactionResult:
    domain: str
    name: str
    ok: bool
    elapsed_ms: float | None
    error: str | None
    details: dict[str, Any]
    browser_infra_error: bool


def _safe_str(x: Any, *, max_len: int = 500) -> str:
    s = str(x or "")
    return s if len(s) <= max_len else s[:max_len]


async def _apply_route_filter(context) -> None:
    try:
        async def _route_filter(route):
            try:
                if route.request.resource_type in {"image", "media", "font"}:
                    await route.abort()
                    return
            except Exception:
                pass
            await route.continue_()

        await context.route("**/*", _route_filter)
    except Exception:
        pass


async def run_synthetic_transactions(
    *,
    domain: str,
    base_url: str,
    browser: Browser,
    transactions: list[dict[str, Any]],
    timeout_seconds: float = 35.0,
) -> list[SyntheticTransactionResult]:
    out: list[SyntheticTransactionResult] = []
    cleaned_domain = str(domain or "").strip().lower()
    base = str(base_url or "").strip()
    timeout_ms = int(max(1.0, float(timeout_seconds)) * 1000)

    for tx in transactions:
        if not isinstance(tx, dict):
            continue
        name = str(tx.get("name") or "transaction").strip()[:120]
        steps = tx.get("steps") or []
        if not isinstance(steps, list) or not steps:
            continue

        started = time.perf_counter()
        context = None
        page = None
        browser_infra_error = False
        try:
            context = await browser.new_context(viewport={"width": 1280, "height": 720})
            await _apply_route_filter(context)
            page = await context.new_page()

            for raw_step in steps[:60]:
                if not isinstance(raw_step, dict):
                    raise ValueError(f"Invalid step: {raw_step!r}")
                typ = str(raw_step.get("type") or "").strip().lower()
                if not typ:
                    raise ValueError(f"Missing step.type: {raw_step!r}")

                if typ == "goto":
                    url = str(raw_step.get("url") or "").strip()
                    if not url:
                        url = base
                    if url.startswith("/"):
                        url = urljoin(base.rstrip("/") + "/", url.lstrip("/"))
                    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    continue

                if typ == "click":
                    sel = str(raw_step.get("selector") or "").strip()
                    if not sel:
                        raise ValueError("click requires selector")
                    await page.click(sel, timeout=timeout_ms)
                    continue

                if typ == "fill":
                    sel = str(raw_step.get("selector") or "").strip()
                    txt = str(raw_step.get("text") or "")
                    if not sel:
                        raise ValueError("fill requires selector")
                    await page.fill(sel, txt, timeout=timeout_ms)
                    continue

                if typ == "press":
                    sel = str(raw_step.get("selector") or "").strip()
                    key = str(raw_step.get("key") or "").strip() or "Enter"
                    if sel:
                        await page.press(sel, key, timeout=timeout_ms)
                    else:
                        await page.keyboard.press(key)
                    continue

                if typ == "wait_for_selector":
                    sel = str(raw_step.get("selector") or "").strip()
                    state = str(raw_step.get("state") or "visible").strip()
                    if not sel:
                        raise ValueError("wait_for_selector requires selector")
                    await page.wait_for_selector(sel, state=state, timeout=timeout_ms)
                    continue

                if typ == "expect_url_contains":
                    value = str(raw_step.get("value") or "").strip()
                    if not value:
                        raise ValueError("expect_url_contains requires value")
                    if value not in (page.url or ""):
                        raise AssertionError(f"url_missing_substring: {value!r} not in {page.url!r}")
                    continue

                if typ == "expect_text":
                    value = str(raw_step.get("text") or "").strip()
                    if not value:
                        raise ValueError("expect_text requires text")
                    body = await page.evaluate("() => document.body?.innerText || ''")
                    if value.lower() not in str(body or "").lower():
                        raise AssertionError(f"text_missing: {value!r}")
                    continue

                if typ in {"sleep", "sleep_ms"}:
                    ms = raw_step.get("ms")
                    try:
                        ms_i = int(ms)
                    except Exception:
                        ms_i = 250
                    await asyncio.sleep(max(0.0, ms_i / 1000.0))
                    continue

                raise ValueError(f"Unknown step.type: {typ!r}")

            elapsed_ms = (time.perf_counter() - started) * 1000.0
            out.append(
                SyntheticTransactionResult(
                    domain=cleaned_domain,
                    name=name,
                    ok=True,
                    elapsed_ms=round(elapsed_ms, 3),
                    error=None,
                    details={"final_url": _safe_str(page.url) if page else None},
                    browser_infra_error=False,
                )
            )
        except PlaywrightTimeoutError as exc:
            browser_infra_error = _is_browser_infra_error(exc)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            title = None
            if page is not None:
                try:
                    title = await page.title()
                except Exception:
                    title = None
            out.append(
                SyntheticTransactionResult(
                    domain=cleaned_domain,
                    name=name,
                    ok=False,
                    elapsed_ms=round(elapsed_ms, 3),
                    error=f"TimeoutError: {exc}",
                    details={
                        "final_url": _safe_str(page.url) if page else None,
                        "title": _safe_str(title) if title is not None else None,
                    },
                    browser_infra_error=browser_infra_error,
                )
            )
        except PlaywrightError as exc:
            browser_infra_error = _is_browser_infra_error(exc)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            title = None
            if page is not None:
                try:
                    title = await page.title()
                except Exception:
                    title = None
            out.append(
                SyntheticTransactionResult(
                    domain=cleaned_domain,
                    name=name,
                    ok=False,
                    elapsed_ms=round(elapsed_ms, 3),
                    error=f"{type(exc).__name__}: {exc}",
                    details={
                        "final_url": _safe_str(page.url) if page else None,
                        "title": _safe_str(title) if title is not None else None,
                    },
                    browser_infra_error=browser_infra_error,
                )
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            out.append(
                SyntheticTransactionResult(
                    domain=cleaned_domain,
                    name=name,
                    ok=False,
                    elapsed_ms=round(elapsed_ms, 3),
                    error=f"{type(exc).__name__}: {exc}",
                    details={"final_url": _safe_str(page.url) if page else None},
                    browser_infra_error=False,
                )
            )
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass

    return out
