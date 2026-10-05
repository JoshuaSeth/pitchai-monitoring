# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tenant test API contracts through real, isolated ASGI routing."""

from __future__ import annotations

import asyncio
import unittest
from http import HTTPStatus
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

import pytest

from domain_checks.dft_test_support import require

from . import auth
from . import db as dbm
from .app import create_app
from .asgi_test_support import request
from .settings import RegistrySettings
from .stepflow import StepFlowValidationError

if TYPE_CHECKING:
    from fastapi import FastAPI

    from domain_checks.config_values import ConfigValue

    from .dashboard_records import Record

_TENANT = dbm.AuthedTenant("test-owner", "test-key")
_HEADERS = {"authorization": "Bearer test-key", "content-type": "application/json"}
_VALID = b'{"name":"fixture","base_url":"https://fixture.invalid","definition":{"steps":[{"type":"goto"}]}}'


class RegistryTestRoutesTests(unittest.IsolatedAsyncioTestCase):
    """Substitute database operations; no lifespan, receiver or real browser."""

    def setUp(self) -> None:
        """Bind an isolated application and one synthetic authenticated tenant."""
        self.settings: RegistrySettings = RegistrySettings(
            alerts_enabled=False, dispatch_enabled=False, strict_base_url_policy=False,
        )
        self.application: FastAPI = create_app(self.settings)
        self.enterContext(patch.object(auth, "get_api_key_by_hash", return_value=_TENANT))

    async def test_creation_admission_and_validation_precede_insertion(self) -> None:
        """Missing/invalid input skips insertion; a valid call retains all defaults."""
        with patch.object(dbm, "insert_test", return_value={"id": "created"}) as insertion:
            for body in (b"", b'{"name":"","base_url":"bad","definition":{}}',
                         _VALID.replace(b'{"type":"goto"}', b'{"type":"unknown"}')):
                response = await request(self.application, "/api/v1/tests", method="POST", headers=_HEADERS, body=body)
                require(condition=response.status_code >= HTTPStatus.BAD_REQUEST, message="invalid creation admitted")
            require(condition=insertion.call_count == 0, message="invalid creation reached insertion")
            response = await request(self.application, "/api/v1/tests", method="POST", headers=_HEADERS, body=_VALID)
            require(condition=response.json() == {"ok": True, "test": {"id": "created"}},
                    message="creation envelope changed")
            values = cast("Record", insertion.call_args.kwargs)
            require(condition=values == {
                "tenant_id": _TENANT.tenant_id, "name": "fixture", "base_url": "https://fixture.invalid",
                "test_kind": "stepflow", "definition": {"name": "test", "steps": [{"type": "goto"}]},
                "interval_seconds": 300, "timeout_seconds": 45, "jitter_seconds": 30,
                "down_after_failures": 2, "up_after_successes": 2,
                "notify_on_recovery": False, "dispatch_on_failure": False,
            }, message="creation arguments or defaults changed")

    async def test_patch_preserves_explicit_null_and_write_read_order(self) -> None:
        """The post-write read may return null; it does not turn into a missing-write error."""
        calls: list[str] = []

        def changed(_settings: RegistrySettings, **_changes: ConfigValue) -> bool:
            calls.append("write")
            return True

        def read(_settings: RegistrySettings, **_changes: ConfigValue) -> None:
            calls.append("read")

        with (
            patch.object(dbm, "patch_test", side_effect=changed) as write,
            patch.object(dbm, "get_test", side_effect=read),
        ):
            response = await request(self.application, "/api/v1/tests/test", method="PATCH", headers=_HEADERS,
                                     body=b'{"base_url":null,"definition":null,"notify_on_recovery":null}')
            require(condition=response.json() == {"ok": True, "test": None}, message="post-write null changed")
            require(condition=calls == ["write", "read"], message="mutation observation order changed")
            require(condition=cast("Record", write.call_args.kwargs) == {
                "tenant_id": _TENANT.tenant_id, "test_id": "test",
                "patch": {"base_url": None, "definition": None, "notify_on_recovery": None},
            }, message="explicit null fields or tenant scope lost")

    async def test_patch_failure_and_invalid_definition_keep_original_boundaries(self) -> None:
        """Failed writes skip the read; StepFlow errors are not creation's translated error."""
        with patch.object(dbm, "patch_test", return_value=False) as write, patch.object(dbm, "get_test") as read:
            response = await request(self.application, "/api/v1/tests/test", method="PATCH",
                                     headers=_HEADERS, body=b"{}")
            require(condition=response.status_code == HTTPStatus.NOT_FOUND, message="failed patch reported success")
            require(condition=read.call_count == 0, message="failed patch reached read")
            with pytest.raises(StepFlowValidationError, match="steps"):
                await request(self.application, "/api/v1/tests/test", method="PATCH", headers=_HEADERS,
                              body=b'{"definition":{}}')
            require(condition=write.call_count == 1, message="invalid patch reached write")

    async def test_disablement_time_and_enable_write_arguments(self) -> None:
        """Invalid times fail before writing and enabling explicitly clears reason/time."""
        with patch.object(dbm, "set_test_disabled", return_value=True) as write:
            response = await request(self.application, "/api/v1/tests/test/disable", method="POST", headers=_HEADERS,
                                     body=b'{"reason":"fixture","until":"not-a-date"}')
            require(condition=response.status_code == HTTPStatus.BAD_REQUEST and write.call_count == 0,
                    message="invalid disablement was written")
            response = await request(self.application, "/api/v1/tests/test/disable", method="POST", headers=_HEADERS,
                                     body=b'{"reason":"fixture","until":123}')
            require(condition=response.json() == {"ok": True} and cast("Record", write.call_args.kwargs) == {
                "tenant_id": _TENANT.tenant_id, "test_id": "test", "disabled": True,
                "reason": "fixture", "until_ts": 123.0,
            }, message="disablement values changed")
            await request(self.application, "/api/v1/tests/test/enable", method="POST", headers=_HEADERS)
            require(condition=cast("Record", write.call_args.kwargs) == {
                "tenant_id": _TENANT.tenant_id, "test_id": "test", "disabled": False, "reason": None, "until_ts": None,
            }, message="enable operation did not clear disablement")

    async def test_lookup_and_trigger_stay_tenant_scoped(self) -> None:
        """Reads and scheduling use the authenticated tenant and preserve missing responses."""
        with (
            patch.object(dbm, "list_tests", return_value=[{"id": "owned"}]) as listing,
            patch.object(dbm, "get_test", return_value=None) as lookup,
            patch.object(dbm, "trigger_run_now", return_value=False) as trigger,
        ):
            response = await request(self.application, "/api/v1/tests", headers=_HEADERS)
            require(condition=response.json() == {"ok": True, "tests": [{"id": "owned"}]}, message="list changed")
            require(condition=cast("Record", listing.call_args.kwargs) == {"tenant_id": _TENANT.tenant_id},
                    message="list tenant changed")
            for path, method in (("/api/v1/tests/foreign", "GET"), ("/api/v1/tests/foreign/run", "POST")):
                response = await request(self.application, path, method=method, headers=_HEADERS)
                require(condition=response.status_code == HTTPStatus.NOT_FOUND, message="missing test admitted")
            for operation in (lookup, trigger):
                require(condition=cast("Record", operation.call_args.kwargs) == {
                    "tenant_id": _TENANT.tenant_id, "test_id": "foreign",
                }, message="lookup/trigger tenant changed")

    async def test_cancellation_does_not_become_success(self) -> None:
        """Cancellation during scheduling leaves the API request cancelled."""
        with (
            patch.object(dbm, "trigger_run_now", side_effect=asyncio.CancelledError("fixture")),
            pytest.raises(asyncio.CancelledError, match="fixture"),
        ):
            await request(self.application, "/api/v1/tests/test/run", method="POST", headers=_HEADERS)
