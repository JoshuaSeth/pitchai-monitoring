# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated registry authentication admission and native dependency tests."""

from __future__ import annotations

import unittest
from secrets import token_hex
from typing import cast
from unittest.mock import patch

import fastapi
import pytest

from domain_checks.dft_test_support import require

from . import auth, db
from .app import create_app
from .asgi_test_support import request
from .settings import RegistrySettings

_MISSING = 401
_INVALID = 403
_UNCONFIGURED = 503
_FIRST_TOKEN = token_hex(16)
_SECOND_TOKEN = token_hex(16)


def _request(header: str = "") -> fastapi.Request:
    application = fastapi.FastAPI()
    headers = [(b"authorization", header.encode("latin-1"))] if header else []
    return fastapi.Request({"type": "http", "app": application, "headers": headers})


def test_settings_remain_late_bound_and_validate_native_state() -> None:
    """Keep identity, late replacement and the legacy RuntimeError failure."""
    req = _request()
    application = cast("fastapi.FastAPI", req.app)
    with pytest.raises(RuntimeError, match="Registry settings not configured"):
        auth.get_settings(req)
    invalid_states: tuple[str | int | dict[str, str] | None, ...] = (None, "invalid", 0, {})
    for invalid in invalid_states:
        application.state.settings = invalid
        with pytest.raises(RuntimeError, match="Registry settings not configured"):
            auth.get_settings(req)
    first = RegistrySettings(admin_token=_FIRST_TOKEN)
    second = RegistrySettings(admin_token=_SECOND_TOKEN)
    application.state.settings = first
    require(condition=auth.get_settings(req) is first, message="settings identity changed")
    application.state.settings = second
    require(condition=auth.get_settings(req) is second, message="settings replacement was pinned")


def test_missing_bearer_precedes_configuration_and_database() -> None:
    """Reject malformed bearer headers before either privileged lookup."""
    settings = RegistrySettings(admin_token="", runner_token="")
    with patch.object(auth, "get_api_key_by_hash", side_effect=AssertionError("unexpected lookup")) as lookup:
        for header in ("", "Basic fixture", "Bearer", "Bearer   "):
            for check in (auth.require_admin, auth.require_runner, auth.require_tenant_auth):
                with pytest.raises(fastapi.HTTPException, match="missing_bearer_token") as error:
                    check(_request(header), settings)
                require(condition=error.value.status_code == _MISSING, message="missing token status changed")
        require(condition=lookup.call_count == 0, message="missing bearer reached database")


def test_roles_retain_independent_configuration_and_failure_order() -> None:
    """Keep unconfigured, invalid and accepted admin/runner results distinct."""
    for check, role in ((auth.require_admin, "admin"), (auth.require_runner, "runner")):
        with pytest.raises(fastapi.HTTPException, match=f"{role}_token_not_configured") as error:
            check(_request("Bearer fixture"), RegistrySettings(admin_token="", runner_token=""))
        require(condition=error.value.status_code == _UNCONFIGURED, message="unconfigured status changed")
        settings = RegistrySettings(admin_token=_FIRST_TOKEN, runner_token=_SECOND_TOKEN)
        with pytest.raises(fastapi.HTTPException, match=f"invalid_{role}_token") as error:
            check(_request("Bearer wrong"), settings)
        require(condition=error.value.status_code == _INVALID, message="invalid token status changed")
        expected = settings.admin_token if role == "admin" else settings.runner_token
        check(_request(f"bEaReR {expected}  "), settings)


def test_tenant_lookup_keeps_hash_and_identity() -> None:
    """Keep one hash-only lookup and distinguish missing from accepted results."""
    settings = RegistrySettings()
    with patch.object(auth, "get_api_key_by_hash", return_value=None) as lookup:
        with pytest.raises(fastapi.HTTPException, match="invalid_token") as error:
            auth.require_tenant_auth(_request("Bearer fixture"), settings)
        require(condition=error.value.status_code == _INVALID, message="tenant rejection status changed")
        lookup.assert_called_once_with(settings, token_hash=auth.hash_token("fixture"))
        lookup.reset_mock()
        lookup.return_value = db.AuthedTenant("fixture-tenant", "fixture-key")
        result = auth.require_tenant_auth(_request("Bearer fixture"), settings)
        require(condition=result == auth.RequestAuth("fixture-tenant", "fixture-key"), message="identity changed")
        lookup.assert_called_once_with(settings, token_hash=auth.hash_token("fixture"))


class NativeAuthTests(unittest.IsolatedAsyncioTestCase):
    """Resolve the real FastAPI dependency without lifespan or external IO."""

    async def test_native_settings_resolution_and_admin_route_admission(self) -> None:
        """Retain 401/403 and admit a valid token to the existing body validation."""
        application = create_app(RegistrySettings(admin_token=_FIRST_TOKEN, alerts_enabled=False))
        database = self.enterContext(patch.object(db, "_connect", side_effect=AssertionError("unexpected database")))
        missing = await request(application, "/api/v1/admin/api_keys", method="POST")
        invalid = await request(application, "/api/v1/admin/api_keys", method="POST",
                                headers={"authorization": "Bearer wrong"})
        valid = await request(application, "/api/v1/admin/api_keys", method="POST",
                              headers={"authorization": f"Bearer {_FIRST_TOKEN}"})
        require(condition=missing.status_code == _MISSING, message="native missing-token outcome changed")
        require(condition=invalid.status_code == _INVALID, message="native invalid-token outcome changed")
        require(condition=valid.body == b'{"detail":"missing_body"}', message="valid auth skipped validation")
        require(condition=database.call_count == 0, message="native auth fixture reached storage")
