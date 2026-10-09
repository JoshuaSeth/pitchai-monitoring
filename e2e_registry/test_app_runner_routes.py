# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated native ASGI runner admission, transaction and notification ordering."""

from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from http import HTTPStatus
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from domain_checks.dft_test_support import require

from . import alerts
from . import app_runner_routes as routes
from . import db as dbm
from .app import create_app
from .asgi_test_support import request
from .runner_transport import RegistryHttpClient
from .settings import RegistrySettings

if TYPE_CHECKING:
    from fastapi import FastAPI

    from .dashboard_records import Record

_HEADERS = {"authorization": "Bearer runner-fixture", "content-type": "application/json"}
_PATH = "/api/v1/runner/runs/run/complete"
_OUTCOME = dbm.CompletionOutcome(
    updated=True, alerted_down=True, recovered_up=True, effective_ok=True, fail_streak=2,
    success_streak=2, tenant_id="tenant", test_id="test", test_name="Fixture", run_id="run",
)
_RUNNER_KEY = "runner-fixture"
_DEFAULT_CONNECT_TIMEOUT = 5
_CONFIG = {"down_after_failures": 2, "test_kind": "python", "dispatch_on_failure": 1,
           "notify_on_recovery": 1, "base_url": "https://fixture.invalid"}


class RunnerRoutesTests(unittest.IsolatedAsyncioTestCase):
    """Substitute the DB and alert gateway; do not start application lifespan."""

    def setUp(self) -> None:
        """Record operations across the existing transaction/client/alert boundaries."""
        settings = RegistrySettings(runner_token=_RUNNER_KEY)
        self.application: FastAPI = create_app(settings)
        self.calls: Mock = Mock()
        self.client: MagicMock = MagicMock()
        entering = AsyncMock(return_value=self.client)
        exiting = AsyncMock(return_value=False)
        self.client.__aenter__ = entering
        self.client.__aexit__ = exiting
        self.ops: dict[str, Mock] = {
            "commit": self.enterContext(patch.object(dbm, "complete_run", return_value=_OUTCOME)),
            "config": self.enterContext(patch.object(dbm, "get_test_config_internal", return_value=_CONFIG)),
            "gateway": self.enterContext(patch.object(routes, "RegistryHttpClient", return_value=self.client)),
            "alert": self.enterContext(patch.object(alerts, "maybe_send_failure_alert", new_callable=AsyncMock)),
            "dispatch": self.enterContext(patch.object(
                alerts, "maybe_dispatch_failure_investigation", new_callable=AsyncMock,
            )),
            "enter": entering, "exit": exiting,
        }
        for name, operation in self.ops.items():
            self.calls.attach_mock(operation, name)

    async def test_commit_precedes_failure_dispatch_and_independent_recovery(self) -> None:
        """Both transition flags retain two fresh config reads and their original order."""
        response = await request(self.application, _PATH, method="POST", headers=_HEADERS,
                                 body=b'{"status":" FAIL ","elapsed_ms":42,"artifacts":{"trace_zip":"fixture"}}')
        require(condition=response.json() == {"ok": True, "outcome": _OUTCOME.__dict__}, message="outcome changed")
        require(condition=[call[0] for call in self.calls.mock_calls] == [
            "commit", "gateway", "enter", "config", "alert", "dispatch", "config", "alert", "exit",
        ], message="transaction/notification order changed")
        completion = cast("dbm.RunCompletion", self.ops["commit"].call_args.kwargs["completion"])
        require(condition=completion.status == "fail" and completion.artifacts == {"trace_zip": "fixture"},
                message="normalized completion or artifacts changed")
        require(condition=cast("Record", self.ops["dispatch"].call_args.kwargs["context"]) == {
            "tenant_id": "tenant", "test_id": "test", "test_name": "Fixture", "test_kind": "python",
            "base_url": "https://fixture.invalid", "run_id": "run",
        }, message="dispatch context changed")

    async def test_invalid_body_and_credentials_never_commit(self) -> None:
        """Runner authentication and status validation retain their independent errors."""
        for body in (b"", b'{"status":"unknown"}', b'{"status":""}'):
            response = await request(self.application, _PATH, method="POST", headers=_HEADERS, body=body)
            require(condition=response.status_code >= HTTPStatus.BAD_REQUEST, message="invalid input admitted")
        response = await request(self.application, _PATH, method="POST", body=b'{"status":"fail"}')
        require(condition=response.status_code == HTTPStatus.UNAUTHORIZED, message="missing credential admitted")
        require(condition=self.ops["commit"].call_count == 0 and self.ops["gateway"].call_count == 0,
                message="invalid input reached transaction or transport")

    async def test_unupdated_or_missing_identity_retains_the_client_context(self) -> None:
        """No notification is fabricated; recovery does not require a tenant ID."""
        self.ops["commit"].return_value = replace(_OUTCOME, updated=False)
        await request(self.application, _PATH, method="POST", headers=_HEADERS, body=b'{"status":"pass"}')
        require(condition=[call[0] for call in self.calls.mock_calls] == ["commit", "gateway", "enter", "exit"],
                message="unupdated result changed client lifecycle")
        self.calls.reset_mock()
        self.ops["commit"].return_value = replace(_OUTCOME, tenant_id=None)
        await request(self.application, _PATH, method="POST", headers=_HEADERS, body=b'{"status":"pass"}')
        require(condition=(self.ops["config"].call_count == 1 and self.ops["alert"].call_count == 1
                           and self.ops["dispatch"].call_count == 0),
                message="recovery inherited failure-only tenant requirement")

    async def test_failure_or_cancellation_stops_later_actions_and_closes_context(self) -> None:
        """A failed alert does not dispatch or recover; transaction cancellation opens no client."""
        for error in (RuntimeError("fixture-failure"), asyncio.CancelledError("fixture-cancel")):
            self.calls.reset_mock()
            self.ops["alert"].side_effect = error
            with pytest.raises(type(error), match="fixture"):
                await request(self.application, _PATH, method="POST", headers=_HEADERS, body=b'{"status":"fail"}')
            require(condition=self.ops["dispatch"].call_count == 0 and self.ops["config"].call_count == 1,
                    message="failed alert continued processing")
            require(condition=self.ops["exit"].call_count == 1, message="alert failure skipped client exit")
            self.ops["alert"].side_effect = None
        self.calls.reset_mock()
        self.ops["commit"].side_effect = asyncio.CancelledError("fixture-cancel")
        with pytest.raises(asyncio.CancelledError, match="fixture"):
            await request(self.application, _PATH, method="POST", headers=_HEADERS, body=b'{"status":"fail"}')
        require(condition=self.ops["gateway"].call_count == 0, message="cancelled transaction opened transport")

    async def test_claim_preserves_exact_job_fields_and_default_limit(self) -> None:
        """Jobs preserve order, optional source metadata and the no-body limit of one."""
        claim = dbm.ClaimedRun("run", "test", "tenant", "Fixture", "https://fixture.invalid", 45,
                              "stepflow", {"steps": []}, None, None, None)
        with patch.object(dbm, "claim_due_runs", return_value=[claim]) as claimed:
            response = await request(self.application, "/api/v1/runner/claim", method="POST", headers=_HEADERS)
            require(condition=response.json() == {"ok": True, "jobs": [claim.__dict__]}, message="job fields changed")
            require(condition=claimed.call_args.kwargs == {"max_runs": 1}, message="default limit changed")
            response = await request(self.application, "/api/v1/runner/claim", method="POST", headers=_HEADERS,
                                     body=b'{"max_runs":51}')
            require(condition=response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY and claimed.call_count == 1,
                    message="invalid limit reached claim")

    @staticmethod
    async def test_native_gateway_retains_header_and_httpx_defaults() -> None:
        """Construction/closure uses no requests and retains inherited transport defaults."""
        client = RegistryHttpClient()
        require(condition=client.headers["User-Agent"] == "PitchAI E2E Registry", message="registry user agent changed")
        require(condition=client.timeout.connect == _DEFAULT_CONNECT_TIMEOUT and not client.follow_redirects,
                message="HTTPX defaults changed")
        await client.aclose()
        require(condition=client.is_closed, message="native client did not close")
