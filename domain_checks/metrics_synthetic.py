from __future__ import annotations

import asyncio
import json
import os
import re
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


_ENV_REF_RE = re.compile(r"\$\{([A-Z0-9_]{1,64})\}")


def _substitute_env_refs(text: str) -> str:
    """
    Replace ${VAR} with os.environ['VAR'].
    - If a placeholder exists but the env var is missing, raise ValueError.
    """
    s = str(text or "")
    if "${" not in s:
        return s

    missing: list[str] = []

    def _repl(m: re.Match[str]) -> str:
        key = m.group(1)
        val = os.getenv(key)
        if val is None:
            missing.append(key)
            return ""
        return val

    out = _ENV_REF_RE.sub(_repl, s)
    if missing:
        raise ValueError(f"missing_env_secrets: {sorted(set(missing))}")
    return out


def _write_artifact(path: str, content: str) -> None:
    try:
        p = os.path.abspath(path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        pass


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
    artifacts_dir: str | None = None,
    trace_on_failure: bool = False,
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
        tracing_started = False
        artifact_names: dict[str, str] = {}
        try:
            context = await browser.new_context(viewport={"width": 1280, "height": 720})
            await _apply_route_filter(context)
            page = await context.new_page()

            if trace_on_failure and artifacts_dir:
                try:
                    await context.tracing.start(screenshots=True, snapshots=True, sources=False)
                    tracing_started = True
                except Exception:
                    tracing_started = False

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
                    url = _substitute_env_refs(url)
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
                    txt = _substitute_env_refs(str(raw_step.get("text") or ""))
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

                if typ == "expect_title_contains":
                    value = str(raw_step.get("text") or raw_step.get("value") or "").strip()
                    if not value:
                        raise ValueError("expect_title_contains requires text/value")
                    title = await page.title()
                    if value.lower() not in str(title or "").lower():
                        raise AssertionError(f"title_missing_substring: {value!r} not in {title!r}")
                    continue

                if typ == "expect_selector_count":
                    sel = str(raw_step.get("selector") or "").strip()
                    if not sel:
                        raise ValueError("expect_selector_count requires selector")
                    try:
                        expected = int(raw_step.get("count"))
                    except Exception as exc:
                        raise ValueError("expect_selector_count requires integer count") from exc
                    got = await page.locator(sel).count()
                    if int(got) != int(expected):
                        raise AssertionError(f"selector_count_mismatch: selector={sel!r} got={got} expected={expected}")
                    continue

                if typ == "set_viewport":
                    try:
                        w = int(raw_step.get("width"))
                        h = int(raw_step.get("height"))
                    except Exception as exc:
                        raise ValueError("set_viewport requires width,height ints") from exc
                    await page.set_viewport_size({"width": w, "height": h})
                    continue

                if typ == "screenshot":
                    if artifacts_dir and page is not None:
                        nm = str(raw_step.get("name") or "screenshot").strip() or "screenshot"
                        safe = "".join(ch for ch in nm if ch.isalnum() or ch in ("-", "_"))[:60] or "screenshot"
                        filename = f"{safe}.png"
                        path = os.path.join(str(artifacts_dir), filename)
                        try:
                            await page.screenshot(path=path, full_page=True)
                            artifact_names[f"screenshot_{safe}"] = filename
                        except Exception:
                            pass
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
                    details={"final_url": _safe_str(page.url) if page else None, **artifact_names},
                    browser_infra_error=False,
                )
            )
            # Success: stop tracing without exporting (keep overhead low).
            if tracing_started and context is not None:
                try:
                    await context.tracing.stop()
                except Exception:
                    pass
        except PlaywrightTimeoutError as exc:
            browser_infra_error = _is_browser_infra_error(exc)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            title = None
            if page is not None:
                try:
                    title = await page.title()
                except Exception:
                    title = None
            # Failure artifacts.
            if artifacts_dir and page is not None:
                try:
                    failure_name = "failure.png"
                    await page.screenshot(path=os.path.join(str(artifacts_dir), failure_name), full_page=True)
                    artifact_names["failure_screenshot"] = failure_name
                except Exception:
                    pass
            if tracing_started and context is not None and artifacts_dir:
                try:
                    trace_name = "trace.zip"
                    await context.tracing.stop(path=os.path.join(str(artifacts_dir), trace_name))
                    artifact_names["trace_zip"] = trace_name
                except Exception:
                    try:
                        await context.tracing.stop()
                    except Exception:
                        pass
            if artifacts_dir:
                _write_artifact(
                    os.path.join(str(artifacts_dir), "run.log"),
                    _safe_str(
                        _safe_str(
                            json.dumps(
                                {
                                    "error": f"TimeoutError: {exc}",
                                    "final_url": _safe_str(page.url) if page else None,
                                    "title": _safe_str(title) if title else None,
                                    "browser_infra_error": bool(browser_infra_error),
                                },
                                ensure_ascii=False,
                                sort_keys=True,
                                indent=2,
                            ),
                            max_len=50_000,
                        ),
                        max_len=50_000,
                    ),
                )
                artifact_names.setdefault("run_log", "run.log")
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
                        **artifact_names,
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
            if artifacts_dir and page is not None:
                try:
                    failure_name = "failure.png"
                    await page.screenshot(path=os.path.join(str(artifacts_dir), failure_name), full_page=True)
                    artifact_names["failure_screenshot"] = failure_name
                except Exception:
                    pass
            if tracing_started and context is not None and artifacts_dir:
                try:
                    trace_name = "trace.zip"
                    await context.tracing.stop(path=os.path.join(str(artifacts_dir), trace_name))
                    artifact_names["trace_zip"] = trace_name
                except Exception:
                    try:
                        await context.tracing.stop()
                    except Exception:
                        pass
            if artifacts_dir:
                _write_artifact(
                    os.path.join(str(artifacts_dir), "run.log"),
                    _safe_str(
                        json.dumps(
                            {
                                "error": f"{type(exc).__name__}: {exc}",
                                "final_url": _safe_str(page.url) if page else None,
                                "title": _safe_str(title) if title else None,
                                "browser_infra_error": bool(browser_infra_error),
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                            indent=2,
                        ),
                        max_len=50_000,
                    ),
                )
                artifact_names.setdefault("run_log", "run.log")
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
                        **artifact_names,
                    },
                    browser_infra_error=browser_infra_error,
                )
            )
        except Exception as exc:
            browser_infra_error = _is_browser_infra_error(exc)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if artifacts_dir and page is not None:
                try:
                    failure_name = "failure.png"
                    await page.screenshot(path=os.path.join(str(artifacts_dir), failure_name), full_page=True)
                    artifact_names["failure_screenshot"] = failure_name
                except Exception:
                    pass
            if tracing_started and context is not None and artifacts_dir:
                try:
                    trace_name = "trace.zip"
                    await context.tracing.stop(path=os.path.join(str(artifacts_dir), trace_name))
                    artifact_names["trace_zip"] = trace_name
                except Exception:
                    try:
                        await context.tracing.stop()
                    except Exception:
                        pass
            if artifacts_dir:
                _write_artifact(
                    os.path.join(str(artifacts_dir), "run.log"),
                    _safe_str(
                        json.dumps(
                            {
                                "error": f"{type(exc).__name__}: {exc}",
                                "final_url": _safe_str(page.url) if page else None,
                                "browser_infra_error": bool(browser_infra_error),
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                            indent=2,
                        ),
                        max_len=50_000,
                    ),
                )
                artifact_names.setdefault("run_log", "run.log")
            out.append(
                SyntheticTransactionResult(
                    domain=cleaned_domain,
                    name=name,
                    ok=False,
                    elapsed_ms=round(elapsed_ms, 3),
                    error=f"{type(exc).__name__}: {exc}",
                    details={"final_url": _safe_str(page.url) if page else None, **artifact_names},
                    browser_infra_error=browser_infra_error,
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
