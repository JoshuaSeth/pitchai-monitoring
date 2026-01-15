from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class DispatchConfig:
    base_url: str
    token: str
    model: str | None = None
    poll_interval_seconds: float = 5.0
    max_wait_seconds: float = 30 * 60
    log_tail_bytes: int = 250_000


def parse_dispatch_response(text: str) -> tuple[str, str]:
    """
    Dispatcher returns: queued:<bundle>:runner:<container_or_already_running_or_error...>
    """
    s = (text or "").strip()
    if not s.startswith("queued:"):
        raise ValueError(f"Unexpected dispatch response: {s!r}")
    rest = s[len("queued:") :]
    if ":runner:" not in rest:
        raise ValueError(f"Unexpected dispatch response: {s!r}")
    bundle, runner = rest.split(":runner:", 1)
    bundle = bundle.strip()
    runner = runner.strip()
    if not bundle:
        raise ValueError(f"Unexpected dispatch response: {s!r}")
    return bundle, runner


def extract_last_agent_message_from_exec_log(text: str) -> str | None:
    for line in reversed((text or "").splitlines()):
        s = line.strip()
        if not s.startswith("{"):
            continue
        try:
            obj = json.loads(s)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if str(obj.get("type") or "") not in {"item.completed", "item.updated"}:
            continue
        item = obj.get("item")
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") != "agent_message":
            continue
        txt = item.get("text")
        if isinstance(txt, str) and txt.strip():
            return txt
    return None


def run_ui_url(base_url: str, bundle: str) -> str:
    return f"{base_url.rstrip('/')}/ui/runs/{bundle}"


async def dispatch_job(
    client: httpx.AsyncClient,
    cfg: DispatchConfig,
    *,
    prompt: str,
    config_toml: str,
    state_key: str | None = None,
    pre_commands: list[str] | None = None,
) -> tuple[str, str]:
    payload: dict[str, Any] = {
        "prompt": prompt,
        "config_toml": config_toml,
    }
    if cfg.model:
        payload["model"] = cfg.model
    if state_key:
        payload["state_key"] = state_key
    if pre_commands:
        payload["pre_commands"] = list(pre_commands)

    url = f"{cfg.base_url.rstrip('/')}/dispatch"
    resp = await client.post(
        url,
        headers={"X-PitchAI-Dispatch-Token": cfg.token},
        json=payload,
        timeout=30.0,
    )
    resp.raise_for_status()
    return parse_dispatch_response(resp.text)


async def get_run_status(client: httpx.AsyncClient, cfg: DispatchConfig, *, bundle: str) -> dict[str, Any]:
    url = f"{cfg.base_url.rstrip('/')}/runs/{bundle}/status"
    resp = await client.get(
        url,
        headers={"X-PitchAI-Dispatch-Token": cfg.token},
        timeout=20.0,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("Unexpected dispatcher status response (not a JSON object)")
    return data


async def get_run_record(client: httpx.AsyncClient, cfg: DispatchConfig, *, bundle: str) -> dict[str, Any]:
    url = f"{cfg.base_url.rstrip('/')}/runs/{bundle}/record"
    resp = await client.get(
        url,
        headers={"X-PitchAI-Dispatch-Token": cfg.token},
        timeout=20.0,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("Unexpected dispatcher record response (not a JSON object)")
    return data


def is_terminal_queue_state(queue_state: Any) -> bool:
    return str(queue_state or "") in {"processed", "failed", "runner_error"}


async def wait_for_terminal_status(client: httpx.AsyncClient, cfg: DispatchConfig, *, bundle: str) -> dict[str, Any]:
    deadline = time.monotonic() + max(1.0, cfg.max_wait_seconds)
    last: dict[str, Any] = {}

    while True:
        try:
            last = await get_run_status(client, cfg, bundle=bundle)
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                # Older dispatcher versions may not expose `/runs/<bundle>/status`. Fall back to `/record`.
                record = await get_run_record(client, cfg, bundle=bundle)
                last = {"queue_state": record.get("status"), "record": record}
            else:
                raise
        if is_terminal_queue_state(last.get("queue_state")):
            return last
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Timed out waiting for dispatcher run to finish (bundle={bundle})")
        await asyncio.sleep(max(0.5, cfg.poll_interval_seconds))


async def _get_log_tail(
    client: httpx.AsyncClient, cfg: DispatchConfig, *, bundle: str, max_bytes: int
) -> str:
    url = f"{cfg.base_url.rstrip('/')}/runs/{bundle}/log"
    head = await client.get(
        url,
        headers={"X-PitchAI-Dispatch-Token": cfg.token},
        params={"offset": 0, "max_bytes": 1},
        timeout=20.0,
    )
    head.raise_for_status()
    head_data = head.json()
    if not isinstance(head_data, dict) or not head_data.get("exists"):
        return ""

    size = int(head_data.get("size") or 0)
    max_bytes = max(1, min(int(max_bytes), 5_000_000))
    offset = max(0, size - max_bytes)

    tail = await client.get(
        url,
        headers={"X-PitchAI-Dispatch-Token": cfg.token},
        params={"offset": offset, "max_bytes": max_bytes},
        timeout=30.0,
    )
    tail.raise_for_status()
    tail_data = tail.json()
    if not isinstance(tail_data, dict):
        return ""
    return str(tail_data.get("content") or "")


async def get_last_agent_message(client: httpx.AsyncClient, cfg: DispatchConfig, *, bundle: str) -> str | None:
    tail = await _get_log_tail(client, cfg, bundle=bundle, max_bytes=cfg.log_tail_bytes)
    return extract_last_agent_message_from_exec_log(tail)
