# Copyright (c) 2026 PitchAI. All rights reserved.
"""Asynchronous dispatcher escalation lifecycle."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx

from domain_checks.dispatch_client import (
    dispatch_job,
    extract_last_agent_message_from_exec_log,
    extract_last_error_message_from_exec_log,
    get_last_agent_message,
    get_run_log_tail,
    run_ui_url,
    wait_for_terminal_status,
)
from domain_checks.monitor_dispatch_config import CODEX_CONFIG_TOML, DOCKER_PRE_COMMAND
from domain_checks.monitor_dispatch_models import QueuedDispatch
from domain_checks.monitor_dispatch_outcomes import (
    handle_boundary_failure,
    handle_http_failure,
    handle_quota_failure,
    store_outcome,
)
from domain_checks.monitor_dispatch_state import dispatch_is_enabled
from domain_checks.telegram import (
    redact_telegram_response,
    send_telegram_message,
    send_telegram_message_chunked,
)

if TYPE_CHECKING:
    from domain_checks.dispatch_client import DispatchConfig
    from domain_checks.monitor_dispatch_models import DispatchOutcome, DispatchRequest
    from domain_checks.monitor_runtime_state import RuntimeState
    from domain_checks.telegram import TelegramConfig
    from domain_checks.types import JsonObject

LOGGER = logging.getLogger("service-monitoring")


@dataclass
class DispatchCoordinator:
    """Schedule, deduplicate, and record dispatcher escalation tasks."""

    http_client: httpx.AsyncClient
    telegram: TelegramConfig
    config: DispatchConfig | None
    dispatch_state: JsonObject
    runtime_state: RuntimeState
    tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)

    def schedule(self, request: DispatchRequest) -> None:
        """Schedule a request unless the same state key is already running."""
        if not dispatch_is_enabled(self.config, self.dispatch_state):
            return
        active = self.tasks.get(request.state_key)
        if active is not None and not active.done():
            LOGGER.info("Dispatch already running state_key=%s", request.state_key)
            return
        self.tasks[request.state_key] = asyncio.create_task(self._run(request))

    def prune(self) -> None:
        """Observe completed tasks and remove them from the active set."""
        for key, task in list(self.tasks.items()):
            if not task.done():
                continue
            task.result()
            del self.tasks[key]

    async def _run(self, request: DispatchRequest) -> None:
        config = self.config
        if config is None:
            return
        started = time.time()
        try:
            await self._execute(request, config, started)
        except httpx.HTTPStatusError as exc:
            await self._http_failure(request, exc, started)
        except (httpx.HTTPError, TimeoutError, RuntimeError, ValueError) as exc:
            await self._boundary_failure(request, exc, started)

    async def _execute(self, request: DispatchRequest, config: DispatchConfig, started: float) -> None:
        bundle, runner = await dispatch_job(
            self.http_client,
            config,
            prompt=request.prompt,
            config_toml=CODEX_CONFIG_TOML,
            state_key=request.state_key,
            pre_commands=[DOCKER_PRE_COMMAND],
        )
        queued = QueuedDispatch(bundle=bundle, runner=runner, started=started)
        await self._finish(request, config, queued)

    async def _finish(
        self,
        request: DispatchRequest,
        config: DispatchConfig,
        queued: QueuedDispatch,
    ) -> None:
        status = await wait_for_terminal_status(self.http_client, config, bundle=queued.bundle)
        queue_state = str(status.get("queue_state") or "")
        ui_url = run_ui_url(config.base_url, queued.bundle)
        tail = await get_run_log_tail(self.http_client, config, bundle=queued.bundle)
        message = extract_last_agent_message_from_exec_log(tail)
        if not message:
            message = await get_last_agent_message(self.http_client, config, bundle=queued.bundle)
        if message:
            await self._forward_message(request, queued.bundle, ui_url, message)
            self._record(
                request,
                {
                    "started_ts": queued.started,
                    "bundle": queued.bundle,
                    "runner": queued.runner,
                    "queue_state": queue_state,
                    "ui_url": ui_url,
                    "ok": True,
                    "error": None,
                    "agent_message": message[:12_000],
                },
            )
            return
        error = (extract_last_error_message_from_exec_log(tail) or "").strip()
        if self._is_quota_error(error):
            await self._quota_failure(request, ui_url, error)
        else:
            suffix = f" Last error: {error[:300]}" if error else ""
            await send_telegram_message(
                self.http_client,
                self.telegram,
                f"{request.title} finished (bundle={queued.bundle}) but no agent message was found.{suffix} {ui_url}",
            )
        self._record(
            request,
            {
                "started_ts": queued.started,
                "bundle": queued.bundle,
                "runner": queued.runner,
                "queue_state": queue_state,
                "ui_url": ui_url,
                "ok": queue_state == "processed",
                "error": error[:800] or "no_agent_message",
                "agent_message": None,
            },
        )

    async def _forward_message(self, request: DispatchRequest, bundle: str, ui_url: str, message: str) -> None:
        ok, responses = await send_telegram_message_chunked(
            self.http_client,
            self.telegram,
            f"{request.title} (bundle={bundle})\n{ui_url}\n\n{message}",
        )
        LOGGER.info(
            "Dispatch finished title=%s telegram_ok=%s telegram_last=%s",
            request.title,
            ok,
            redact_telegram_response(responses[-1] if responses else {}),
        )

    @staticmethod
    def _is_quota_error(error: str) -> bool:
        lowered = error.lower()
        return any(marker in lowered for marker in ("quota exceeded", "billing details", "insufficient_quota"))

    async def _quota_failure(self, request: DispatchRequest, ui_url: str, error: str) -> None:
        await handle_quota_failure(self.http_client, self.telegram, self.dispatch_state, ui_url)
        LOGGER.warning("Dispatch disabled due to runner quota title=%s error=%s", request.title, error[:500])

    async def _http_failure(
        self,
        request: DispatchRequest,
        error: httpx.HTTPStatusError,
        started: float,
    ) -> None:
        queue_state = await handle_http_failure(
            self.http_client,
            self.telegram,
            self.dispatch_state,
            request,
            error,
        )
        self._record(
            request,
            {
                "started_ts": started,
                "bundle": None,
                "runner": None,
                "queue_state": queue_state,
                "ui_url": "",
                "ok": False,
                "error": str(error)[:800],
                "agent_message": None,
            },
        )

    async def _boundary_failure(self, request: DispatchRequest, error: Exception, started: float) -> None:
        description = await handle_boundary_failure(self.http_client, self.telegram, request, error)
        self._record(
            request,
            {
                "started_ts": started,
                "bundle": None,
                "runner": None,
                "queue_state": "exception",
                "ui_url": "",
                "ok": False,
                "error": description[:800],
                "agent_message": None,
            },
        )

    def _record(self, request: DispatchRequest, outcome: DispatchOutcome) -> None:
        store_outcome(self.runtime_state, request, outcome)
