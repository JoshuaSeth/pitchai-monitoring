from __future__ import annotations

import os

import httpx
import pytest

from domain_checks.dispatch_client import (
    DispatchConfig,
    dispatch_job,
    extract_last_agent_message_from_exec_log,
    extract_last_error_message_from_exec_log,
    get_last_agent_message,
    get_run_log_tail,
    run_ui_url,
    wait_for_terminal_status,
)


pytestmark = pytest.mark.live


if os.getenv("RUN_LIVE_DISPATCH_TESTS") != "1":
    pytest.skip("Set RUN_LIVE_DISPATCH_TESTS=1 to run live Dispatcher/Codex smoke test", allow_module_level=True)


@pytest.mark.asyncio
async def test_dispatcher_live_smoke() -> None:
    token = os.getenv("PITCHAI_DISPATCH_TOKEN")
    if not token:
        pytest.skip("Missing PITCHAI_DISPATCH_TOKEN", allow_module_level=False)

    base_url = (os.getenv("PITCHAI_DISPATCH_BASE_URL") or "https://dispatch.pitchai.net").strip()
    model = os.getenv("PITCHAI_DISPATCH_MODEL")

    cfg = DispatchConfig(
        base_url=base_url,
        token=token,
        model=(model.strip() if model and model.strip() else None),
        poll_interval_seconds=5.0,
        max_wait_seconds=10 * 60,
        log_tail_bytes=250_000,
    )

    config_toml = "\n".join(
        [
            'approval_policy = "never"',
            'sandbox_mode = "danger-full-access"',
            "hide_agent_reasoning = true",
            "",
        ]
    )
    prompt = "Reply with exactly: ok"

    async with httpx.AsyncClient() as client:
        bundle, _runner = await dispatch_job(client, cfg, prompt=prompt, config_toml=config_toml)
        status = await wait_for_terminal_status(client, cfg, bundle=bundle)
        queue_state = status.get("queue_state")
        assert queue_state in {"processed", "failed", "runner_error"}

        ui = run_ui_url(cfg.base_url, bundle)
        tail = await get_run_log_tail(client, cfg, bundle=bundle)
        msg = extract_last_agent_message_from_exec_log(tail) or await get_last_agent_message(client, cfg, bundle=bundle)

        if queue_state != "processed":
            err = extract_last_error_message_from_exec_log(tail) or ""
            err_l = err.lower()
            if "quota exceeded" in err_l or "billing details" in err_l or "insufficient_quota" in err_l:
                pytest.skip(f"Dispatcher runner quota exceeded (rotate PITCHAI_DISPATCH_TOKEN). {ui}")
            pytest.fail(f"Dispatcher run not processed queue_state={queue_state!r} err={err!r} {ui}")

        assert msg and msg.strip().lower() == "ok"
