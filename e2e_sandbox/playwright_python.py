from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from domain_checks.common_check import _is_browser_infra_error, find_chromium_executable  # noqa: SLF001


RESULT_PREFIX = "E2E_RESULT_JSON="


def _safe_str(x: Any, *, max_len: int = 2000) -> str:
    s = str(x or "")
    return s if len(s) <= max_len else s[:max_len]


def _write_text(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", errors="replace")
    except Exception:
        pass


async def _route_filter(context) -> None:
    # Reduce bandwidth/CPU for monitoring-style tests.
    try:
        async def _handler(route):
            try:
                if route.request.resource_type in {"image", "media", "font"}:
                    await route.abort()
                    return
            except Exception:
                pass
            await route.continue_()

        await context.route("**/*", _handler)
    except Exception:
        pass


def _load_module_from_path(path: Path):
    p = path.resolve()
    name = f"submitted_e2e_{abs(hash(str(p)))}"
    spec = importlib.util.spec_from_file_location(name, str(p))
    if spec is None or spec.loader is None:
        raise RuntimeError("could_not_load_test_module")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _pick_entry(mod) -> Callable[..., Any]:
    fn = getattr(mod, "run", None)
    if callable(fn):
        return fn
    fn = getattr(mod, "main", None)
    if callable(fn):
        return fn
    raise RuntimeError("test_file_must_define_run_or_main")


@dataclass(frozen=True)
class RunResult:
    status: str  # pass|fail|infra_degraded
    elapsed_ms: float | None
    error_kind: str | None
    error_message: str | None
    final_url: str | None
    title: str | None
    artifacts: dict[str, str]
    browser_infra_error: bool

    def to_json(self) -> str:
        return json.dumps(
            {
                "status": self.status,
                "elapsed_ms": self.elapsed_ms,
                "error_kind": self.error_kind,
                "error_message": self.error_message,
                "final_url": self.final_url,
                "title": self.title,
                "artifacts": self.artifacts,
                "browser_infra_error": self.browser_infra_error,
            },
            ensure_ascii=False,
            sort_keys=True,
        )


async def _run_one(
    *,
    test_file: Path,
    base_url: str,
    artifacts_dir: Path,
    timeout_seconds: float,
    trace_on_failure: bool,
) -> RunResult:
    started = time.perf_counter()
    artifacts: dict[str, str] = {}
    timeout_ms = int(max(1.0, float(timeout_seconds)) * 1000.0)

    chromium_path = find_chromium_executable()
    if not chromium_path:
        raise RuntimeError("missing_chromium_executable")

    mod = _load_module_from_path(test_file)
    entry = _pick_entry(mod)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-sync",
                "--metrics-recording-only",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-features=site-per-process",
                # Avoid renderer crashes when /dev/shm is tiny.
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        await _route_filter(context)
        page = await context.new_page()
        page.set_default_timeout(timeout_ms)
        tracing_started = False
        if trace_on_failure:
            try:
                await context.tracing.start(screenshots=True, snapshots=True, sources=False)
                tracing_started = True
            except Exception:
                tracing_started = False

        try:
            # Preferred contract: `async def run(page, base_url, artifacts_dir): ...`
            # Fallback: `def main(base_url, artifacts_dir): ...`
            if getattr(mod, "run", None) is entry:
                res = entry(page, base_url, str(artifacts_dir))
            else:
                res = entry(base_url, str(artifacts_dir))
            if asyncio.iscoroutine(res):
                await res

            elapsed_ms = (time.perf_counter() - started) * 1000.0
            final_url = _safe_str(getattr(page, "url", None))
            title = None
            try:
                title = _safe_str(await page.title(), max_len=500)
            except Exception:
                title = None

            if tracing_started:
                try:
                    await context.tracing.stop()
                except Exception:
                    pass

            return RunResult(
                status="pass",
                elapsed_ms=round(elapsed_ms, 3),
                error_kind=None,
                error_message=None,
                final_url=final_url or None,
                title=title,
                artifacts=artifacts,
                browser_infra_error=False,
            )
        except (PlaywrightTimeoutError, PlaywrightError, Exception) as exc:
            browser_infra_error = _is_browser_infra_error(exc)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            final_url = None
            title = None
            try:
                final_url = _safe_str(getattr(page, "url", None)) or None
            except Exception:
                final_url = None
            try:
                title = _safe_str(await page.title(), max_len=500)
            except Exception:
                title = None

            # Best-effort failure artifacts.
            try:
                failure_name = "failure.png"
                await page.screenshot(path=str(artifacts_dir / failure_name), full_page=True)
                artifacts["failure_screenshot"] = failure_name
            except Exception:
                pass

            if tracing_started:
                try:
                    trace_name = "trace.zip"
                    await context.tracing.stop(path=str(artifacts_dir / trace_name))
                    artifacts["trace_zip"] = trace_name
                except Exception:
                    try:
                        await context.tracing.stop()
                    except Exception:
                        pass

            status = "infra_degraded" if browser_infra_error else "fail"
            err_kind = type(exc).__name__
            err_msg = _safe_str(exc, max_len=2000)
            # Also persist a structured run.log so humans can inspect without container logs.
            _write_text(
                artifacts_dir / "run.log",
                json.dumps(
                    {
                        "status": status,
                        "error_kind": err_kind,
                        "error_message": err_msg,
                        "final_url": final_url,
                        "title": title,
                        "browser_infra_error": bool(browser_infra_error),
                        "traceback": _safe_str(traceback.format_exc(), max_len=50_000),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                ),
            )
            artifacts.setdefault("run_log", "run.log")

            return RunResult(
                status=status,
                elapsed_ms=round(elapsed_ms, 3),
                error_kind=err_kind,
                error_message=err_msg,
                final_url=final_url,
                title=title,
                artifacts=artifacts,
                browser_infra_error=bool(browser_infra_error),
            )
        finally:
            try:
                await page.close()
            except Exception:
                pass
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass


async def _amain(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Run a submitted Playwright Python test file.")
    ap.add_argument("--test-file", required=True)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--artifacts-dir", required=True)
    ap.add_argument("--timeout-seconds", type=float, default=45.0)
    ap.add_argument("--trace-on-failure", action="store_true")
    args = ap.parse_args(argv)

    test_file = Path(args.test_file).resolve()
    artifacts_dir = Path(args.artifacts_dir).resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = await _run_one(
            test_file=test_file,
            base_url=str(args.base_url).strip(),
            artifacts_dir=artifacts_dir,
            timeout_seconds=float(args.timeout_seconds),
            trace_on_failure=bool(args.trace_on_failure),
        )
    except Exception as exc:
        # Fatal errors (e.g. module import) are treated as fail; infra if browser error heuristic says so.
        infra = _is_browser_infra_error(exc)
        status = "infra_degraded" if infra else "fail"
        artifacts: dict[str, str] = {}
        _write_text(
            artifacts_dir / "run.log",
            json.dumps(
                {
                    "status": status,
                    "error_kind": type(exc).__name__,
                    "error_message": _safe_str(exc, max_len=2000),
                    "browser_infra_error": bool(infra),
                    "traceback": _safe_str(traceback.format_exc(), max_len=50_000),
                },
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ),
        )
        artifacts["run_log"] = "run.log"
        result = RunResult(
            status=status,
            elapsed_ms=None,
            error_kind=type(exc).__name__,
            error_message=_safe_str(exc, max_len=2000),
            final_url=None,
            title=None,
            artifacts=artifacts,
            browser_infra_error=bool(infra),
        )

    # Emit machine-readable output for the runner.
    sys.stdout.write(RESULT_PREFIX + result.to_json() + "\n")
    sys.stdout.flush()
    return 0 if result.status == "pass" else 1


def main() -> None:
    # Ensure predictable HOME for Playwright temp files inside read-only sandboxes.
    os.environ.setdefault("HOME", "/tmp")
    try:
        rc = asyncio.run(_amain(sys.argv[1:]))
    except KeyboardInterrupt:
        rc = 130
    sys.exit(int(rc))


if __name__ == "__main__":
    main()

