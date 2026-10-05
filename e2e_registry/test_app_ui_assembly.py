# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated UI admission, display fallbacks and startup IO order."""

from __future__ import annotations

import asyncio
import unittest
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock, patch

import pytest

from domain_checks.dft_test_support import require

from . import db as dbm
from .app import create_app
from .app_host_policy import RegistryHostPolicy
from .app_ui_presentation import SourcePreview, display_artifacts, normalize_display_tests
from .asgi_test_support import request
from .auth import hash_token
from .settings import RegistrySettings

if TYPE_CHECKING:
    from fastapi import FastAPI

    from domain_checks.config_values import ConfigValue

    from .dashboard_records import Record

_TENANT = dbm.AuthedTenant("fixture", "fixture-key")
_COOKIE = {"cookie": "e2e_token_hash=fixture-hash"}


class RegistryUiAssemblyTests(unittest.IsolatedAsyncioTestCase):
    """Use native ASGI/templates, with database and filesystem operations substituted."""

    def setUp(self) -> None:
        """Construct the app without running its startup hooks or opening storage."""
        self.application: FastAPI = create_app(RegistrySettings(alerts_enabled=False, dispatch_enabled=False))
        self.lookup: Mock = self.enterContext(patch.object(dbm, "get_api_key_by_hash", return_value=_TENANT))
        self.enterContext(patch.object(dbm, "_connect", side_effect=AssertionError("unexpected database")))

    async def test_login_validation_cookie_and_logout(self) -> None:
        """Only a nonblank recognized key obtains the original hash-only cookie."""
        headers = {"content-type": "application/x-www-form-urlencoded"}
        response = await request(self.application, "/ui/login", method="POST", headers=headers, body=b"api_key=+")
        require(condition=b"Missing API key" in response.body and self.lookup.call_count == 0,
                message="empty login reached lookup")
        self.lookup.return_value = None
        response = await request(self.application, "/ui/login", method="POST", headers=headers, body=b"api_key=fixture")
        require(condition=b"Invalid API key" in response.body, message="unknown key admitted")
        self.lookup.return_value = _TENANT
        response = await request(self.application, "/ui/login", method="POST", headers=headers, body=b"api_key=fixture")
        cookie = dict(response.headers)[b"set-cookie"]
        require(condition=(hash_token("fixture").encode() in cookie
                           and b"HttpOnly" in cookie and b"SameSite=lax" in cookie),
                message="login cookie changed")
        response = await request(self.application, "/ui/logout")
        require(condition=b"Max-Age=0" in dict(response.headers)[b"set-cookie"], message="logout did not clear cookie")

    async def test_read_redirect_and_mutation_auth_remain_distinct(self) -> None:
        """Unauthenticated reads redirect while writes retain the original 401 response."""
        with patch.object(dbm, "trigger_run_now") as write, patch.object(dbm, "get_test") as read:
            response = await request(self.application, "/ui/tests/foreign")
            require(condition=dict(response.headers)[b"location"] == b"/ui/login", message="read redirect changed")
            response = await request(self.application, "/ui/tests/foreign/run", method="POST")
            require(condition=response.status_code == HTTPStatus.UNAUTHORIZED, message="write auth changed")
            require(condition=write.call_count == 0 and read.call_count == 0,
                    message="unauthenticated access reached DB")

    async def test_disablement_parsing_and_false_write_redirect(self) -> None:
        """Invalid times skip writes; failed writes retain their explicit redirect message."""
        headers = {**_COOKIE, "content-type": "application/x-www-form-urlencoded"}
        with patch.object(dbm, "set_test_disabled", return_value=False) as write:
            response = await request(self.application, "/ui/tests/test/disable", method="POST", headers=headers,
                                     body=b"until=bad")
            require(condition=(b"Invalid+until+value" in dict(response.headers)[b"location"] and write.call_count == 0),
                    message="invalid time reached write")
            response = await request(self.application, "/ui/tests/test/disable", method="POST", headers=headers,
                                     body=b"until=123")
            require(condition=b"Disable%20failed" in dict(response.headers)[b"location"],
                    message="failed write changed")
            require(condition=cast("Record", write.call_args.kwargs) == {
                "tenant_id": "fixture", "test_id": "test", "disabled": True,
                "reason": "temporary disable", "until_ts": 123.0,
            }, message="disable values changed")

    @staticmethod
    async def test_display_normalization_and_json_fallbacks() -> None:
        """Malformed display fields remain values rather than becoming healthy observations."""
        records: list[Record] = [{"effective_ok": "1", "fail_streak": "bad", "success_streak": None}]
        normalize_display_tests(records)
        require(condition=records == [{"effective_ok": 1, "fail_streak": "bad", "success_streak": None}],
                message="display normalization changed")
        cases: list[tuple[ConfigValue, ConfigValue]] = [
            ("[1]", [1]), ("true", True), ("bad", {}), ("0", {}), ({"a": 1}, {"a": 1}), ([], {}),
        ]
        for value, expected in cases:
            require(condition=display_artifacts(value) == expected, message="artifact fallback changed")

    @staticmethod
    async def test_preview_filename_survives_read_failure_and_truncation() -> None:
        """The optional source preview keeps filename knowledge without inventing file text."""
        preview = SourcePreview()
        directory = str(Path.cwd())
        test: Record = {"test_kind": "python", "source_relpath": "fixture.py"}
        with (patch.object(Path, "exists", return_value=True), patch.object(Path, "is_file", return_value=True),
              patch.object(Path, "read_text", side_effect=OSError("fixture"))):
            preview.read(directory, test)
        require(condition=preview.filename == "fixture.py" and preview.text is None, message="read failure changed")
        with (patch.object(Path, "exists", return_value=True), patch.object(Path, "is_file", return_value=True),
              patch.object(Path, "read_text", return_value="x" * 80_001)):
            preview.read(directory, test)
        require(condition=preview.text == "x" * 80_000 + "\n...truncated...", message="preview bound changed")

    async def test_startup_order_and_independent_directory_failures(self) -> None:
        """Schema failure is loud; directory/quarantine errors retain their original boundary."""
        calls = Mock()
        with (
            patch.object(dbm, "ensure_schema") as schema,
            patch.object(Path, "mkdir", side_effect=[OSError("first"), OSError("second")]) as directories,
            patch.object(RegistryHostPolicy, "quarantine_disallowed_tests", return_value=2) as quarantine,
            self.assertLogs("e2e-registry", level="WARNING") as logs,
        ):
            for name, operation in (("schema", schema), ("directory", directories), ("quarantine", quarantine)):
                calls.attach_mock(operation, name)
            await self.application.router.startup()
        require(condition=[call[0] for call in calls.mock_calls] == ["schema", "directory", "directory", "quarantine"],
                message="startup IO order changed")
        require(condition="count=2" in logs.output[0], message="quarantine notice changed")
        with (patch.object(dbm, "ensure_schema", side_effect=RuntimeError("fixture-schema")),
              patch.object(Path, "mkdir") as directories, pytest.raises(RuntimeError, match="fixture-schema")):
            await self.application.router.startup()
        require(condition=directories.call_count == 0, message="failed schema reached directory preparation")

    async def test_startup_quarantine_failure_and_request_cancellation(self) -> None:
        """Quarantine failure is logged; unrelated request cancellation still propagates."""
        with (patch.object(dbm, "ensure_schema"), patch.object(Path, "mkdir"),
              patch.object(RegistryHostPolicy, "quarantine_disallowed_tests", side_effect=RuntimeError("fixture")),
              self.assertLogs("e2e-registry", level="ERROR") as logs):
            await self.application.router.startup()
        require(condition="Failed to quarantine" in logs.output[0], message="quarantine failure was hidden")
        with (patch.object(dbm, "list_tests", side_effect=asyncio.CancelledError("fixture")),
              pytest.raises(asyncio.CancelledError, match="fixture")):
            await request(self.application, "/ui/tests", headers=_COOKIE)
