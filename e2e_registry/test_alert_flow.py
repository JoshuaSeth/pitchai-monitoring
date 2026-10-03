# Copyright (c) 2026 PitchAI. All rights reserved.
"""Guard the registry's existing alert order with local synthetic responses only."""

from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from domain_checks.dft_test_support import require, require_error

from . import alerts
from .alert_records import DispatchRecord
from .settings import RegistrySettings

if TYPE_CHECKING:
    from domain_checks.event_bus_delivery import JsonObject


def settings_fixture() -> RegistrySettings:
    """Return explicit synthetic routing that is intercepted before any transport."""
    credential = "isolated fixture, never sent"
    return RegistrySettings(dispatch_enabled=True, dispatch_token=credential, dispatch_model="fixture-model",
                            dispatch_base_url="https://dispatch.invalid", alerts_enabled=True,
                            telegram_bot_token=credential, telegram_chat_id="fixture-private")


class AlertFlowTests(unittest.IsolatedAsyncioTestCase):
    """Persist/send ordering, admission and cancellation at the actual entry points."""

    @staticmethod
    async def test_dispatch_admission_does_not_touch_client() -> None:
        """Disabled or unconfigured dispatch creates no request, task or persistence."""
        client = cast("AsyncClient", MagicMock(spec=AsyncClient))
        with patch("e2e_registry.alerts.dispatch_job", new_callable=AsyncMock) as dispatch:
            for settings in (replace(settings_fixture(), dispatch_enabled=False),
                             replace(settings_fixture(), dispatch_token="")):
                await alerts.maybe_dispatch_failure_investigation(http_client=client, settings=settings, prompt="test")
        dispatch.assert_not_awaited()

    @staticmethod
    async def test_alert_admission_and_unsent_result() -> None:
        """The original token/chat checks remain, and transport failure is only logged."""
        client = cast("AsyncClient", MagicMock(spec=AsyncClient))
        send = AsyncMock(return_value=(False, [{"ok": False, "error": "synthetic unsent"}]))
        with patch("e2e_registry.alerts.send_telegram_message_chunked", new=send):
            for settings in (replace(settings_fixture(), alerts_enabled=False),
                             replace(settings_fixture(), telegram_bot_token=""),
                             replace(settings_fixture(), telegram_chat_id="")):
                await alerts.maybe_send_failure_alert(http_client=client, settings=settings, msg="fixture")
            send.assert_not_awaited()
            await alerts.maybe_send_failure_alert(http_client=client, settings=settings_fixture(), msg="fixture")
        send.assert_awaited_once()

    @staticmethod
    async def test_dispatch_terminal_branches_persist_before_notice() -> None:
        """Message, failed and processed-without-message retain distinct records."""
        cases = (("processed", "answer", None), ("failed", None, "failure"),
                 ("processed", None, "no_agent_message"), ("failed", "answer", None))
        for state, message, error in cases:
            await verify_terminal_case(state, message, error)

    @staticmethod
    async def test_record_failure_is_logged_without_swallowing_cancellation() -> None:
        """A DB failure stays best effort; cancellation must not become a notice."""
        record = DispatchRecord("key", "bundle", "ui", "failed", None, "fault")
        with patch.object(DispatchRecord, "write", new=AsyncMock(side_effect=OSError("synthetic DB refusal"))):
            await record.persist(settings_fixture(), {})
        with patch.object(DispatchRecord, "write", new=AsyncMock(side_effect=asyncio.CancelledError("cancel"))):
            results = await asyncio.gather(record.persist(settings_fixture(), {}), return_exceptions=True)
        require(condition=isinstance(results[0], asyncio.CancelledError), message="DB cancellation suppressed")

    @staticmethod
    async def test_dispatch_error_propagates_before_record() -> None:
        """Ordinary remote failure does not fabricate a terminal record or forward."""
        client = cast("AsyncClient", MagicMock(spec=AsyncClient))
        with (patch("e2e_registry.alerts.dispatch_job", new=AsyncMock(side_effect=RuntimeError("synthetic refusal"))),
              patch.object(DispatchRecord, "persist", new_callable=AsyncMock) as persist,
              require_error(RuntimeError, "synthetic refusal")):
            await alerts.maybe_dispatch_failure_investigation(http_client=client,
                                                             settings=settings_fixture(), prompt="x")
        persist.assert_not_awaited()


async def verify_terminal_case(state: str, message: str | None, error: str | None) -> None:
    """Exercise actual orchestration with captured DB/transport operations."""
    steps: list[str] = []
    records: list[DispatchRecord] = []
    notices: list[str] = []
    context: JsonObject = {"original": [1, 2]}
    client = cast("AsyncClient", MagicMock(spec=AsyncClient))

    def persist(record: DispatchRecord, settings: RegistrySettings, received: JsonObject | None) -> None:
        require(condition=settings == settings_fixture() and received is context, message="context/settings changed")
        records.append(record)
        steps.append("persist")

    def send(*, http_client: AsyncClient, settings: RegistrySettings, msg: str) -> None:
        require(condition=http_client is client and settings == settings_fixture(), message="client/settings changed")
        notices.append(msg)
        steps.append("send")

    dispatch = AsyncMock(return_value=("bundle", "runner"))
    status = AsyncMock(return_value={"queue_state": state})
    tail = AsyncMock(return_value="synthetic log")
    with (patch("e2e_registry.alerts.dispatch_job", new=dispatch),
          patch("e2e_registry.alerts.wait_for_terminal_status", new=status),
          patch("e2e_registry.alerts.get_run_log_tail", new=tail),
          patch("e2e_registry.alerts.extract_last_agent_message_from_exec_log", return_value=message),
          patch("e2e_registry.alerts.extract_last_error_message_from_exec_log", return_value=error),
          patch.object(DispatchRecord, "persist", autospec=True, side_effect=persist),
          patch("e2e_registry.alerts.maybe_send_failure_alert", new=AsyncMock(side_effect=send))):
        await alerts.maybe_dispatch_failure_investigation(http_client=client, settings=settings_fixture(),
                                                         prompt="fixture", context=context)
    dispatch.assert_awaited_once()
    status.assert_awaited_once()
    tail.assert_awaited_once()
    require(condition=records == [DispatchRecord("e2e-registry.failure", "bundle",
                                                "https://dispatch.invalid/ui/runs/bundle", state, message, error)],
            message="terminal record changed")
    expected_steps = ["persist", "send"] if message or state != "processed" else ["persist"]
    require(condition=steps == expected_steps, message="record/notice order changed")
    expected_notice = records[0].notice()
    require(condition=notices == ([] if expected_notice is None else [expected_notice]), message="notice changed")
