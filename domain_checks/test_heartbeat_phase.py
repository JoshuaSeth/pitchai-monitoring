# Copyright (c) 2026 PitchAI. All rights reserved.
"""Heartbeat boundary tests with isolated HTTP and no outgoing delivery."""

from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

from .cycle_channels import CycleChannels
from .dft_test_support import require
from .dispatch_records import DispatchRecords
from .heartbeat_phase import ExternalHeartbeat, HeartbeatObservation, HeartbeatPhase, HeartbeatSchedule
from .heartbeat_settings import HeartbeatSettings
from .telegram import TelegramConfig

if TYPE_CHECKING:
    from httpx import AsyncClient

NOW = datetime(2026, 10, 3, 10, 1, tzinfo=UTC)
SYNTHETIC_CREDENTIAL = "fixture-value"


def _phase() -> HeartbeatPhase:
    return HeartbeatPhase(HeartbeatSettings(enabled=True, timezone="UTC", times=[time(10), time(10, 1)]),
                          HeartbeatSchedule(UTC, NOW - timedelta(hours=1), 120, {}),
                          ExternalHeartbeat(enabled=False, base_url="", token="", timeout_seconds=3))


def _observation() -> HeartbeatObservation:
    return HeartbeatObservation({}, {}, ["synthetic.invalid: disabled"], None, None, None)


def _channels(client: AsyncClient) -> CycleChannels:
    return CycleChannels(client, TelegramConfig("synthetic-no-send", "synthetic-no-send"),
                         None, {}, DispatchRecords(), {})


def _client() -> tuple[AsyncClient, AsyncMock]:
    """Return a substituted API boundary that rejects unexpected requests."""
    get = AsyncMock(side_effect=AssertionError("unexpected HTTP request"))
    return cast("AsyncClient", MagicMock(get=get)), get


class TestHeartbeatSchedule(unittest.IsolatedAsyncioTestCase):
    """Exercise due windows, attempt recording, failure and cancellation ownership."""

    @staticmethod
    async def test_order_dedup_and_unsent_return() -> None:
        """Processing an unsent result preserves the existing per-label daily dedup."""
        phase = _phase()
        sent = phase.schedule.sent
        transport = AsyncMock(return_value=(False, []))
        client, _ = _client()
        with (patch("domain_checks.heartbeat_phase.datetime", new=MagicMock(wraps=datetime,
                    now=MagicMock(return_value=NOW))),
              patch("domain_checks.heartbeat_phase.send_telegram_message_chunked", new=transport)):
            for _ in range(3):
                await phase.run(_channels(client), _observation())
        require(condition=transport.await_count == len(phase.settings.times), message="unexpected repeated attempt")
        require(condition=sent == {"10:00": "2026-10-03", "10:01": "2026-10-03"}, message="label/date dedup changed")
        require(condition=phase.schedule.sent is sent, message="sent-map identity changed")

    async def test_due_interval_boundaries(self) -> None:
        """The start is inclusive; the tolerance end is exclusive, without startup catch-up."""
        for seconds, expected in ((-1, 0), (0, 1), (119, 1), (120, 0), (3600, 0)):
            with self.subTest(seconds=seconds):
                phase = _phase()
                phase.settings.times[:] = [time(10)]
                transport = AsyncMock(return_value=(False, []))
                client, _ = _client()
                with (patch("domain_checks.heartbeat_phase.datetime", new=MagicMock(wraps=datetime,
                            now=MagicMock(return_value=NOW.replace(minute=0) + timedelta(seconds=seconds)))),
                      patch("domain_checks.heartbeat_phase.send_telegram_message_chunked", new=transport)):
                    await phase.run(_channels(client), _observation())
                require(condition=transport.await_count == expected, message="due interval boundary changed")

    async def test_failure_and_cancellation_do_not_mark_attempt(self) -> None:
        """Transport errors propagate with sent-map ownership retained by the cycle."""
        for failure in (RuntimeError("synthetic failure"), asyncio.CancelledError()):
            with self.subTest(failure=type(failure).__name__):
                phase = _phase()
                client, _ = _client()
                with (patch("domain_checks.heartbeat_phase.datetime", new=MagicMock(wraps=datetime,
                            now=MagicMock(return_value=NOW))),
                      patch("domain_checks.heartbeat_phase.send_telegram_message_chunked",
                            new=AsyncMock(side_effect=failure))):
                    result = await asyncio.gather(phase.run(_channels(client), _observation()),
                                                  return_exceptions=True)
                require(condition=isinstance(result[0], type(failure)), message="transport failure suppressed")
                require(condition=not phase.schedule.sent, message="failed attempt marked sent")

    @staticmethod
    async def test_empty_cycle_does_not_sample_clock() -> None:
        """Absent gathered observations skip the whole heartbeat phase."""
        now = MagicMock(side_effect=AssertionError("empty phase sampled clock"))
        client, _ = _client()
        with patch("domain_checks.heartbeat_phase.datetime", new=MagicMock(now=now)):
            await _phase().run(_channels(client), HeartbeatObservation({}, {}, [], None, None, None))
        now.assert_not_called()


class TestExternalHeartbeat(unittest.IsolatedAsyncioTestCase):
    """Only a local HTTP mock is callable; registry diagnostics stay optional."""

    @staticmethod
    async def test_mapping_and_request_contract() -> None:
        """Use the original URL, bearer header and timeout without persisting a token."""
        client, get = _client()
        get.side_effect = None
        get.return_value = MagicMock(json=MagicMock(return_value={"ok": True, "nested": [1, {"value": None}]}))
        external = ExternalHeartbeat(enabled=True, base_url="https://registry.invalid/",
                                     token=SYNTHETIC_CREDENTIAL, timeout_seconds=3.5)
        require(condition=await external.read(client) == {"ok": True, "nested": [1, {"value": None}]},
                message="registry JSON changed")
        get.assert_awaited_once_with("https://registry.invalid/api/v1/status/summary",
                                    headers={"Authorization": f"Bearer {SYNTHETIC_CREDENTIAL}"}, timeout=3.5)
        require(condition=SYNTHETIC_CREDENTIAL not in repr(external), message="token exposed in repr")

    async def test_optional_diagnostics(self) -> None:
        """Absent configuration skips HTTP; invalid responses retain their existing diagnostics."""
        client, _ = _client()
        require(condition=await ExternalHeartbeat(enabled=False, base_url="https://registry.invalid",
                token=SYNTHETIC_CREDENTIAL, timeout_seconds=3).read(client) is None, message="disabled registry read")
        require(condition=await ExternalHeartbeat(enabled=True, base_url="", token=SYNTHETIC_CREDENTIAL,
                timeout_seconds=3).read(client) is None, message="empty registry read")
        require(condition=await ExternalHeartbeat(enabled=True, base_url="https://registry.invalid", token="",
                timeout_seconds=3).read(client) == {"ok": False, "error": "missing_e2e_registry_token"},
                message="missing token diagnostic changed")
        for payload in ("text", 0, False, None):
            with self.subTest(payload=payload):
                client, get = _client()
                get.side_effect = None
                get.return_value = MagicMock(json=MagicMock(return_value=payload))
                require(condition=await ExternalHeartbeat(enabled=True, base_url="https://registry.invalid",
                        token=SYNTHETIC_CREDENTIAL, timeout_seconds=3).read(client)
                        == {"ok": False, "error": "invalid_e2e_registry_response"},
                        message="invalid registry diagnostic changed")

    @staticmethod
    async def test_observation_failure_and_cancellation() -> None:
        """Ordinary HTTP failures become diagnostics while task cancellation remains loud."""
        external = ExternalHeartbeat(enabled=True, base_url="https://registry.invalid",
                                     token=SYNTHETIC_CREDENTIAL, timeout_seconds=3)
        client, _ = _client()
        with patch.object(client, "get", new=AsyncMock(side_effect=OSError("synthetic"))):
            require(condition=await external.read(client) == {"ok": False, "error": "OSError: synthetic"},
                    message="registry failure diagnostic changed")
        with patch.object(client, "get", new=AsyncMock(side_effect=asyncio.CancelledError)):
            result = await asyncio.gather(external.read(client), return_exceptions=True)
        require(condition=isinstance(result[0], asyncio.CancelledError), message="registry cancellation suppressed")
