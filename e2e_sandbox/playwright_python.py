# Copyright (c) 2026 PitchAI. All rights reserved.
"""Run the existing submitted Python test protocol inside its browser context."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import anyio
from playwright.async_api import async_playwright

from domain_checks.browser_errors import is_browser_infra_error
from domain_checks.browser_launch import base_chromium_arguments
from domain_checks.common_check import find_chromium_executable

from .python_browser import BrowserSession
from .python_browser import route_filter as _route_filter
from .python_execution import PreparedSubmission
from .python_module import load_module_from_path as _load_module_from_path
from .python_module import pick_entry as _pick_entry
from .python_result import RESULT_PREFIX, RunFailureBoundary, RunResult
from .python_result import safe_str as _safe_str
from .python_result import write_text as _write_text

__all__ = ["RESULT_PREFIX", "RunResult", "_load_module_from_path", "_pick_entry", "_route_filter", "_safe_str",
           "_write_text", "main", "run_one"]
MISSING_CHROMIUM_MESSAGE = "missing_chromium_executable"


async def run_one(
    *, test_file: Path, base_url: str, artifacts_dir: Path, timeout_seconds: float, trace_on_failure: bool,
) -> RunResult:
    """Preserve module selection, browser arguments, execution and cleanup order.

    Returns:
        The existing pass/fail/infra result for this submitted invocation.

    Raises:
        RuntimeError: Chromium is missing or no result was produced.
    """
    started = time.perf_counter()
    timeout_ms = int(max(1.0, float(timeout_seconds)) * 1000.0)
    chromium_path = find_chromium_executable()
    if not chromium_path:
        raise RuntimeError(MISSING_CHROMIUM_MESSAGE)
    module = _load_module_from_path(test_file)
    prepared = PreparedSubmission(started, base_url, artifacts_dir, timeout_ms, module, _pick_entry(module))
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True, executable_path=chromium_path,
            args=[*base_chromium_arguments(), "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        await _route_filter(context)
        page = await context.new_page()
        page.set_default_timeout(prepared.timeout_ms)
        session = BrowserSession(browser, context, page)
        await session.start_trace(enabled=trace_on_failure)
        return await prepared.run(session)


_run_one = run_one


@dataclass
class SandboxArguments(argparse.Namespace):
    """Exact CLI fields produced by the unchanged argument parser."""

    test_file: str = ""
    base_url: str = ""
    artifacts_dir: str = ""
    timeout_seconds: float = 45.0
    trace_on_failure: bool = False


def parse_arguments(argv: list[str]) -> SandboxArguments:
    """Read CLI values and resolve private input/output paths before the async run.

    Returns:
        The original parsed fields, with existing path resolution and mkdir order.
    """
    parser = argparse.ArgumentParser(description="Run a submitted Playwright Python test file.")
    _ = parser.add_argument("--test-file", required=True)
    _ = parser.add_argument("--base-url", required=True)
    _ = parser.add_argument("--artifacts-dir", required=True)
    _ = parser.add_argument("--timeout-seconds", type=float, default=45.0)
    _ = parser.add_argument("--trace-on-failure", action="store_true")
    args = parser.parse_args(argv, namespace=SandboxArguments())
    args.test_file = str(Path(args.test_file).resolve())
    args.artifacts_dir = str(Path(args.artifacts_dir).resolve())
    Path(args.artifacts_dir).mkdir(parents=True, exist_ok=True)
    return args


async def _amain(argv: list[str]) -> int:
    """Emit one machine-readable result from the existing CLI options.

    Returns:
        Zero for pass and one for existing failure/infra cases.

    Raises:
        RuntimeError: No result was produced by the invocation or failure boundary.
    """
    args = parse_arguments(argv)
    artifacts_dir = Path(args.artifacts_dir)
    result = None
    failure = RunFailureBoundary()
    with failure:
        result = await _run_one(test_file=Path(args.test_file), base_url=str(args.base_url).strip(),
                                artifacts_dir=artifacts_dir, timeout_seconds=float(args.timeout_seconds),
                                trace_on_failure=bool(args.trace_on_failure))
    if failure.error is not None:
        result = fatal_result(failure.error, failure.traceback_text, artifacts_dir)
    if result is None:
        message = "submitted_test_did_not_produce_a_result"
        raise RuntimeError(message)
    _ = sys.stdout.write(RESULT_PREFIX + result.to_json() + "\n")
    sys.stdout.flush()
    return 0 if result.status == "pass" else 1


def fatal_result(error: Exception, trace: str, directory: Path) -> RunResult:
    """Retain CLI-level failures, including import errors before browser allocation.

    Returns:
        The existing fatal result and best-effort structured log.
    """
    infra = is_browser_infra_error(error)
    status = "infra_degraded" if infra else "fail"
    _write_text(directory / "run.log", json.dumps({
        "status": status, "error_kind": type(error).__name__, "error_message": _safe_str(error, max_len=2000),
        "browser_infra_error": bool(infra), "traceback": _safe_str(trace, max_len=50_000),
    }, ensure_ascii=False, sort_keys=True, indent=2))
    return RunResult(status, None, type(error).__name__, _safe_str(error, max_len=2000), None, None,
                     {"run_log": "run.log"}, bool(infra))


def main() -> None:
    """Use the asyncio backend while preserving HOME default and CLI exit behavior."""
    os.environ.setdefault("HOME", "/tmp")
    rc = 130
    with suppress(KeyboardInterrupt):
        rc = anyio.run(_amain, sys.argv[1:], backend="asyncio")
    sys.exit(int(rc))


if __name__ == "__main__":
    main()
