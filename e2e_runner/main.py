from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from playwright.async_api import Browser, async_playwright

from domain_checks.common_check import find_chromium_executable
from domain_checks.metrics_synthetic import run_synthetic_transactions


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return int(default)
    try:
        return int(str(raw).strip())
    except Exception:
        return int(default)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    s = str(raw).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


@dataclass(frozen=True)
class RunnerConfig:
    registry_base_url: str
    runner_token: str
    artifacts_dir: str
    poll_seconds: float
    concurrency: int
    trace_on_failure: bool


def load_config() -> RunnerConfig:
    base = (os.getenv("E2E_REGISTRY_BASE_URL") or "http://127.0.0.1:8111").strip()
    tok = (os.getenv("E2E_REGISTRY_RUNNER_TOKEN") or "").strip()
    artifacts = (os.getenv("E2E_ARTIFACTS_DIR") or "/data/e2e-artifacts").strip()
    poll = float(os.getenv("E2E_RUNNER_POLL_SECONDS") or "5")
    conc = _env_int("E2E_RUNNER_CONCURRENCY", 1)
    trace_on_failure = _env_bool("E2E_RUNNER_TRACE_ON_FAILURE", False)
    return RunnerConfig(
        registry_base_url=base,
        runner_token=tok,
        artifacts_dir=artifacts,
        poll_seconds=max(0.5, poll),
        concurrency=max(1, min(conc, 10)),
        trace_on_failure=trace_on_failure,
    )


async def _launch_browser(p) -> Browser:
    chromium_path = find_chromium_executable()
    if not chromium_path:
        raise RuntimeError("Could not find chromium executable (set CHROMIUM_PATH)")

    args = [
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
    ]

    # Avoid renderer crashes when /dev/shm is tiny.
    try:
        st = os.statvfs("/dev/shm")
        shm_bytes = int(st.f_frsize) * int(st.f_blocks)
    except Exception:
        shm_bytes = 0
    if shm_bytes and shm_bytes < (512 * 1024 * 1024):
        args.insert(1, "--disable-dev-shm-usage")

    return await p.chromium.launch(headless=True, executable_path=chromium_path, args=args)


async def _claim_jobs(client: httpx.AsyncClient, cfg: RunnerConfig) -> list[dict[str, Any]]:
    resp = await client.post(
        f"{cfg.registry_base_url.rstrip('/')}/api/v1/runner/claim",
        headers={"Authorization": f"Bearer {cfg.runner_token}"},
        json={"max_runs": int(cfg.concurrency)},
        timeout=20.0,
    )
    resp.raise_for_status()
    data = resp.json()
    jobs = data.get("jobs") if isinstance(data, dict) else None
    return jobs if isinstance(jobs, list) else []


async def _complete_job(
    client: httpx.AsyncClient,
    cfg: RunnerConfig,
    *,
    run_id: str,
    payload: dict[str, Any],
) -> None:
    resp = await client.post(
        f"{cfg.registry_base_url.rstrip('/')}/api/v1/runner/runs/{run_id}/complete",
        headers={"Authorization": f"Bearer {cfg.runner_token}"},
        json=payload,
        timeout=30.0,
    )
    resp.raise_for_status()


async def _run_one_job(browser: Browser, cfg: RunnerConfig, client: httpx.AsyncClient, job: dict[str, Any]) -> None:
    run_id = str(job.get("run_id") or "").strip()
    test_id = str(job.get("test_id") or "").strip()
    tenant_id = str(job.get("tenant_id") or "").strip()
    base_url = str(job.get("base_url") or "").strip()
    timeout_seconds = float(job.get("timeout_seconds") or 45.0)
    definition = job.get("definition")

    started_at_ts = time.time()
    artifacts: dict[str, Any] = {}
    status = "infra_degraded"
    elapsed_ms = None
    error_kind = None
    error_message = None
    final_url = None
    title = None

    out_dir = Path(cfg.artifacts_dir) / tenant_id / test_id / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        transactions = [definition] if isinstance(definition, dict) else []
        if not transactions:
            status = "fail"
            error_kind = "invalid_definition"
            error_message = "definition must be an object"
        else:
            results = await run_synthetic_transactions(
                domain=test_id or "test",
                base_url=base_url,
                browser=browser,
                transactions=transactions,
                timeout_seconds=timeout_seconds,
                artifacts_dir=str(out_dir),
                trace_on_failure=bool(cfg.trace_on_failure),
            )
            r = results[0] if results else None
            if r is None:
                status = "fail"
                error_kind = "runner_error"
                error_message = "no_result"
            elif r.ok:
                status = "pass"
                elapsed_ms = r.elapsed_ms
                final_url = (r.details or {}).get("final_url")
            else:
                elapsed_ms = r.elapsed_ms
                final_url = (r.details or {}).get("final_url")
                title = (r.details or {}).get("title")
                error_message = r.error
                # r.error is already "Type: msg" format.
                error_kind = "assertion_failed"
                if r.browser_infra_error:
                    status = "infra_degraded"
                    error_kind = "browser_infra_error"
                else:
                    status = "fail"
                # Surface any artifact names collected by the synthetic runner.
                if isinstance(r.details, dict):
                    for k in ("failure_screenshot", "trace_zip", "run_log"):
                        v = r.details.get(k)
                        if isinstance(v, str) and v.strip():
                            artifacts[k] = v.strip()
                    for k, v in r.details.items():
                        if not isinstance(k, str):
                            continue
                        if not k.startswith("screenshot_"):
                            continue
                        if isinstance(v, str) and v.strip():
                            artifacts[k] = v.strip()
    except Exception as exc:
        status = "infra_degraded"
        error_kind = type(exc).__name__
        error_message = str(exc)

    finished_at_ts = time.time()
    payload = {
        "status": status,
        "elapsed_ms": float(elapsed_ms) if elapsed_ms is not None else None,
        "error_kind": error_kind,
        "error_message": error_message,
        "final_url": final_url,
        "title": title,
        "artifacts": artifacts,
        "started_at_ts": float(started_at_ts),
        "finished_at_ts": float(finished_at_ts),
    }

    # Always report completion, even if the run payload indicates infra degradation.
    await _complete_job(client, cfg, run_id=run_id, payload=payload)


async def run_loop(cfg: RunnerConfig) -> int:
    if not cfg.runner_token:
        raise RuntimeError("Missing E2E_REGISTRY_RUNNER_TOKEN")

    async with httpx.AsyncClient(headers={"User-Agent": "PitchAI E2E Runner"}) as client:
        async with async_playwright() as p:
            browser: Browser | None = None
            launch_fail_count = 0
            launch_next_try_ts = 0.0

            async def _ensure_browser(now_ts: float) -> Browser | None:
                nonlocal browser, launch_fail_count, launch_next_try_ts

                if browser is not None:
                    try:
                        if browser.is_connected():
                            return browser
                    except Exception:
                        pass
                    try:
                        await browser.close()
                    except Exception:
                        pass
                    browser = None

                if launch_next_try_ts > 0.0 and now_ts < launch_next_try_ts:
                    return None

                try:
                    browser = await _launch_browser(p)
                    launch_fail_count = 0
                    launch_next_try_ts = 0.0
                    return browser
                except Exception:
                    launch_fail_count += 1
                    backoff = min(120.0, 2.0 * (2 ** min(launch_fail_count, 6)))
                    launch_next_try_ts = now_ts + backoff
                    browser = None
                    return None

            try:
                while True:
                    # Do not claim runs if we can't execute them (avoids locking runs in "pending").
                    now_ts = time.time()
                    b = await _ensure_browser(now_ts)
                    if b is None:
                        await asyncio.sleep(max(1.0, cfg.poll_seconds))
                        continue

                    jobs = []
                    try:
                        jobs = await _claim_jobs(client, cfg)
                    except Exception:
                        jobs = []
                    if not jobs:
                        await asyncio.sleep(cfg.poll_seconds)
                        continue
                    for job in jobs:
                        if not isinstance(job, dict):
                            continue
                        try:
                            await _run_one_job(b, cfg, client, job)
                        except Exception:
                            # Avoid crashing the runner loop due to one bad job.
                            continue
            finally:
                if browser is not None:
                    try:
                        await browser.close()
                    except Exception:
                        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run a single claim+execute loop then exit")
    args = parser.parse_args()

    cfg = load_config()
    if args.once:
        # For smoke tests: run loop for one cycle.
        async def _once() -> None:
            async with httpx.AsyncClient(headers={"User-Agent": "PitchAI E2E Runner"}) as client:
                jobs = await _claim_jobs(client, cfg)
                if not jobs:
                    return
                async with async_playwright() as p:
                    try:
                        browser = await _launch_browser(p)
                    except Exception as exc:
                        # Best-effort: release locks by completing claimed runs as infra-degraded.
                        for job in jobs:
                            if not isinstance(job, dict):
                                continue
                            rid = str(job.get("run_id") or "").strip()
                            if not rid:
                                continue
                            try:
                                await _complete_job(
                                    client,
                                    cfg,
                                    run_id=rid,
                                    payload={
                                        "status": "infra_degraded",
                                        "elapsed_ms": None,
                                        "error_kind": "browser_launch_failed",
                                        "error_message": f"{type(exc).__name__}: {exc}",
                                        "final_url": None,
                                        "title": None,
                                        "artifacts": {},
                                        "started_at_ts": time.time(),
                                        "finished_at_ts": time.time(),
                                    },
                                )
                            except Exception:
                                continue
                        return

                    try:
                        for job in jobs:
                            if isinstance(job, dict):
                                await _run_one_job(browser, cfg, client, job)
                    finally:
                        await browser.close()

        asyncio.run(_once())
        return

    asyncio.run(run_loop(cfg))


if __name__ == "__main__":
    main()
