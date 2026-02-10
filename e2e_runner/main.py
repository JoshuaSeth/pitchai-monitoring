from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from playwright.async_api import Browser, async_playwright

from domain_checks.common_check import find_chromium_executable
from domain_checks.metrics_synthetic import run_synthetic_transactions


LOGGER = logging.getLogger("e2e-runner")


RESULT_PREFIX = "E2E_RESULT_JSON="
_RESULT_LINE_RE = re.compile(r"^E2E_RESULT_JSON=(\{.*\})\s*$")


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
    tests_dir: str
    poll_seconds: float
    concurrency: int
    trace_on_failure: bool
    code_exec_mode: str  # local|docker (docker requires /var/run/docker.sock)


def load_config() -> RunnerConfig:
    base = (os.getenv("E2E_REGISTRY_BASE_URL") or "http://127.0.0.1:8111").strip()
    tok = (os.getenv("E2E_REGISTRY_RUNNER_TOKEN") or "").strip()
    artifacts = (os.getenv("E2E_ARTIFACTS_DIR") or "/data/e2e-artifacts").strip()
    tests_dir = (os.getenv("E2E_TESTS_DIR") or "/tests").strip()
    poll = float(os.getenv("E2E_RUNNER_POLL_SECONDS") or "5")
    conc = _env_int("E2E_RUNNER_CONCURRENCY", 1)
    trace_on_failure = _env_bool("E2E_RUNNER_TRACE_ON_FAILURE", False)
    code_exec_mode = (os.getenv("E2E_RUNNER_CODE_EXEC_MODE") or "local").strip().lower()
    if code_exec_mode not in {"local", "docker"}:
        code_exec_mode = "local"
    return RunnerConfig(
        registry_base_url=base,
        runner_token=tok,
        artifacts_dir=artifacts,
        tests_dir=tests_dir,
        poll_seconds=max(0.5, poll),
        concurrency=max(1, min(conc, 10)),
        trace_on_failure=trace_on_failure,
        code_exec_mode=code_exec_mode,
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


def _extract_result_json(text: str) -> dict[str, Any] | None:
    """
    Submitted test runners print a single machine-readable line:
      E2E_RESULT_JSON={...}
    We scan stdout/stderr for the last such line.
    """
    if not text:
        return None
    last = None
    for line in str(text).splitlines():
        m = _RESULT_LINE_RE.match(line.strip())
        if not m:
            continue
        last = m.group(1)
    if not last:
        return None
    try:
        data = json.loads(last)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _build_sandbox_env(*, base_url: str, artifacts_dir: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    """
    Minimize secret leakage: do not inherit the runner container's full env.
    """
    keep_keys = {"PATH", "LANG", "TZ", "CHROMIUM_PATH", "NODE_PATH", "PUPPETEER_EXECUTABLE_PATH", "PUPPETEER_SKIP_DOWNLOAD"}
    env: dict[str, str] = {}
    for k, v in os.environ.items():
        if k in keep_keys or k.startswith("LC_") or k.startswith("PUPPETEER_"):
            env[str(k)] = str(v)
    env.setdefault("HOME", "/tmp")
    env["BASE_URL"] = str(base_url)
    env["ARTIFACTS_DIR"] = str(artifacts_dir)
    if extra:
        for k, v in extra.items():
            env[str(k)] = str(v)
    return env


async def _run_code_local(
    *,
    cfg: RunnerConfig,
    kind: str,
    test_file: Path,
    base_url: str,
    artifacts_dir: Path,
    timeout_seconds: float,
    trace_on_failure: bool,
) -> tuple[dict[str, Any] | None, str]:
    """
    Execute code tests as separate local processes (still isolated from runner env).
    Returns (parsed_result_json, combined_output).
    """
    cmd: list[str]
    if kind == "playwright_python":
        cmd = [
            sys.executable,
            "-m",
            "e2e_sandbox.playwright_python",
            "--test-file",
            str(test_file),
            "--base-url",
            str(base_url),
            "--artifacts-dir",
            str(artifacts_dir),
            "--timeout-seconds",
            str(timeout_seconds),
        ]
        if trace_on_failure:
            cmd.append("--trace-on-failure")
    elif kind == "puppeteer_js":
        cmd = [
            "node",
            "/app/e2e_sandbox/puppeteer_js_runner.js",
            "--test-file",
            str(test_file),
            "--base-url",
            str(base_url),
            "--artifacts-dir",
            str(artifacts_dir),
            "--timeout-seconds",
            str(timeout_seconds),
        ]
    else:
        raise RuntimeError(f"unsupported_code_kind: {kind}")

    env = _build_sandbox_env(base_url=base_url, artifacts_dir=str(artifacts_dir))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=max(5.0, float(timeout_seconds) + 15.0))
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        raise

    out = (out_b or b"").decode("utf-8", errors="replace")
    err = (err_b or b"").decode("utf-8", errors="replace")
    combined = "\n".join([out.strip(), err.strip()]).strip()
    parsed = _extract_result_json("\n".join([out, err]))
    return parsed, combined


async def _run_one_job(browser: Browser | None, cfg: RunnerConfig, client: httpx.AsyncClient, job: dict[str, Any]) -> None:
    run_id = str(job.get("run_id") or "").strip()
    test_id = str(job.get("test_id") or "").strip()
    tenant_id = str(job.get("tenant_id") or "").strip()
    base_url = str(job.get("base_url") or "").strip()
    timeout_seconds = float(job.get("timeout_seconds") or 45.0)
    test_kind = str(job.get("test_kind") or "stepflow").strip().lower() or "stepflow"
    definition = job.get("definition")
    source_relpath = str(job.get("source_relpath") or "").strip() or None

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
        if test_kind == "stepflow":
            if browser is None:
                status = "infra_degraded"
                error_kind = "browser_unavailable"
                error_message = "runner has no browser instance"
            else:
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
        else:
            if test_kind not in {"playwright_python", "puppeteer_js"}:
                status = "fail"
                error_kind = "invalid_kind"
                error_message = f"unsupported_test_kind: {test_kind}"
            elif not source_relpath:
                status = "fail"
                error_kind = "missing_source"
                error_message = "source_relpath is required for code tests"
            else:
                test_file = (Path(cfg.tests_dir).resolve() / source_relpath).resolve()
                base_tests = Path(cfg.tests_dir).resolve()
                if base_tests not in test_file.parents:
                    status = "fail"
                    error_kind = "invalid_source_path"
                    error_message = "source_relpath resolves outside tests_dir"
                elif not test_file.exists() or not test_file.is_file():
                    status = "fail"
                    error_kind = "source_not_found"
                    error_message = f"missing_file: {test_file}"
                else:
                    parsed, combined = await _run_code_local(
                        cfg=cfg,
                        kind=test_kind,
                        test_file=test_file,
                        base_url=base_url,
                        artifacts_dir=out_dir,
                        timeout_seconds=timeout_seconds,
                        trace_on_failure=bool(cfg.trace_on_failure),
                    )
                    # Always persist runner stdout/stderr for debugging.
                    try:
                        (out_dir / "runner_output.log").write_text(combined + "\n", encoding="utf-8", errors="replace")
                        artifacts.setdefault("runner_output", "runner_output.log")
                    except Exception:
                        pass

                    if parsed:
                        status = str(parsed.get("status") or "fail").strip().lower()
                        if status not in {"pass", "fail", "infra_degraded"}:
                            status = "fail"
                        elapsed_ms = parsed.get("elapsed_ms")
                        try:
                            elapsed_ms = float(elapsed_ms) if elapsed_ms is not None else None
                        except Exception:
                            elapsed_ms = None
                        error_kind = str(parsed.get("error_kind") or "").strip() or None
                        error_message = str(parsed.get("error_message") or "").strip() or None
                        final_url = str(parsed.get("final_url") or "").strip() or None
                        title = str(parsed.get("title") or "").strip() or None
                        arts = parsed.get("artifacts")
                        if isinstance(arts, dict):
                            for k, v in arts.items():
                                if isinstance(k, str) and isinstance(v, str) and v.strip():
                                    artifacts[k] = v.strip()
                    else:
                        status = "fail"
                        error_kind = "missing_result_json"
                        error_message = "runner output did not include E2E_RESULT_JSON"
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

    LOGGER.info(
        "Starting e2e-runner registry_base_url=%s poll_seconds=%s concurrency=%s trace_on_failure=%s tests_dir=%s code_exec_mode=%s",
        cfg.registry_base_url,
        cfg.poll_seconds,
        cfg.concurrency,
        cfg.trace_on_failure,
        cfg.tests_dir,
        cfg.code_exec_mode,
    )

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
                    LOGGER.info("Chromium launched ok")
                    return browser
                except Exception:
                    launch_fail_count += 1
                    backoff = min(120.0, 2.0 * (2 ** min(launch_fail_count, 6)))
                    launch_next_try_ts = now_ts + backoff
                    browser = None
                    LOGGER.warning("Chromium launch failed; backoff_seconds=%s fail_count=%s", backoff, launch_fail_count)
                    return None

            try:
                while True:
                    jobs = []
                    try:
                        jobs = await _claim_jobs(client, cfg)
                        if jobs:
                            LOGGER.info("Claimed jobs count=%s", len(jobs))
                    except Exception:
                        LOGGER.exception("Claim failed")
                        jobs = []
                    if not jobs:
                        await asyncio.sleep(cfg.poll_seconds)
                        continue

                    # Only launch/restart the shared browser when needed (StepFlow jobs). Code tests
                    # can still run even if the browser subsystem is degraded.
                    needs_browser = False
                    for j in jobs:
                        if not isinstance(j, dict):
                            continue
                        k = str(j.get("test_kind") or "stepflow").strip().lower() or "stepflow"
                        if k == "stepflow":
                            needs_browser = True
                            break

                    b = None
                    if needs_browser:
                        b = await _ensure_browser(time.time())

                    for job in jobs:
                        if not isinstance(job, dict):
                            continue
                        try:
                            k = str(job.get("test_kind") or "stepflow").strip().lower() or "stepflow"
                            await _run_one_job(b if k == "stepflow" else None, cfg, client, job)
                            rid = str(job.get("run_id") or "").strip()
                            tid = str(job.get("test_id") or "").strip()
                            LOGGER.info("Job complete run_id=%s test_id=%s", rid, tid)
                        except Exception:
                            # Avoid crashing the runner loop due to one bad job.
                            rid = str(job.get("run_id") or "").strip()
                            tid = str(job.get("test_id") or "").strip()
                            LOGGER.exception("Job crashed run_id=%s test_id=%s", rid, tid)
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

    log_level = (os.getenv("E2E_RUNNER_LOG_LEVEL") or os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    cfg = load_config()
    if args.once:
        # For smoke tests: run loop for one cycle.
        async def _once() -> None:
            async with httpx.AsyncClient(headers={"User-Agent": "PitchAI E2E Runner"}) as client:
                jobs = await _claim_jobs(client, cfg)
                if not jobs:
                    LOGGER.info("No jobs claimed; exiting --once")
                    return
                async with async_playwright() as p:
                    needs_browser = False
                    for j in jobs:
                        if not isinstance(j, dict):
                            continue
                        k = str(j.get("test_kind") or "stepflow").strip().lower() or "stepflow"
                        if k == "stepflow":
                            needs_browser = True
                            break

                    browser = None
                    if needs_browser:
                        try:
                            browser = await _launch_browser(p)
                        except Exception:
                            LOGGER.warning("Chromium launch failed in --once; StepFlow jobs will be infra_degraded")
                            browser = None

                    try:
                        for job in jobs:
                            if not isinstance(job, dict):
                                continue
                            k = str(job.get("test_kind") or "stepflow").strip().lower() or "stepflow"
                            await _run_one_job(browser if k == "stepflow" else None, cfg, client, job)
                    finally:
                        if browser is not None:
                            await browser.close()

        asyncio.run(_once())
        return

    asyncio.run(run_loop(cfg))


if __name__ == "__main__":
    main()
