# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated registry admission, access and snapshot-cache contracts."""

from __future__ import annotations

import secrets
import unittest
from dataclasses import replace
from ipaddress import IPv4Address
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException, Request

from domain_checks.dft_test_support import require

from . import db as dbm
from . import monitor_dashboard as md
from .app_access import RegistryAccess
from .app_context import RegistryContext, file_mtime
from .app_host_policy import RegistryHostPolicy, host_is_reserved_or_non_public
from .app_inputs import normalize_pitchai_email
from .settings import RegistrySettings

if TYPE_CHECKING:
    from .app_context import MonitorCache

_NOW = 2_000_000_000.0
_EXPECTED_QUARANTINE_WRITES = 2


def _context() -> RegistryContext:
    application = FastAPI()
    application.state.settings = RegistrySettings(
        admin_token="", monitor_token="", strict_base_url_policy=True,
        base_url_allowed_hosts=("allowed.pitchai.net",), base_url_allow_monitored_domains=False,
        monitor_state_path="synthetic-state", monitor_config_path="synthetic-config",
    )
    return RegistryContext(application)


def _request(path: str, headers: list[tuple[bytes, bytes]]) -> Request:
    return Request({"type": "http", "path": path, "headers": headers, "scheme": "https", "server": ("fixture", 443)})


class RegistryBoundaryTests(unittest.IsolatedAsyncioTestCase):
    """No lifecycle, real database, browser, network or outgoing delivery."""

    @staticmethod
    def test_host_policy_keeps_syntax_and_strict_admission_order() -> None:
        """Disabling strict policy does not disable the initial syntax validator."""
        context = _context()
        policy = RegistryHostPolicy(context)
        with pytest.raises(HTTPException, match="base_url_not_allowed_host"):
            policy.validate_base_url("https://example.com")
        with pytest.raises(HTTPException, match="base_url_not_monitored_domain"):
            policy.validate_base_url("https://unlisted.pitchai.net")
        require(condition=policy.validate_base_url("https://allowed.pitchai.net/path") ==
                "https://allowed.pitchai.net/path", message="allowed URL spelling changed")
        context.app.state.settings = replace(context.settings, strict_base_url_policy=False)
        require(condition=policy.validate_base_url("https://example.com") == "https://example.com",
                message="replaced settings not observed")
        with (
            patch("e2e_registry.app_host_policy.validate_base_url", side_effect=ValueError("syntax-first")),
            pytest.raises(ValueError, match="syntax-first"),
        ):
            policy.validate_base_url("bad")

    @staticmethod
    def test_identity_and_numeric_host_boundaries() -> None:
        """Whitespace/foreign identities reject; numeric addresses need no DNS."""
        require(condition=normalize_pitchai_email("Fixture@PitchAI.NET") == "fixture@pitchai.net",
                message="identity casing changed")
        invalid_identities = (
            None, " fixture@pitchai.net", "fixture@pitchai.net ", "fixture@foreign.invalid", "a@@pitchai.net",
        )
        for invalid in invalid_identities:
            require(condition=normalize_pitchai_email(invalid) is None, message="invalid identity admitted")
        for host in (str(IPv4Address(0)), "127.0.0.1", "::1", "10.0.0.1", "service", "a.invalid", "example.com."):
            require(condition=host_is_reserved_or_non_public(host), message="reserved host admitted")
        require(condition=not host_is_reserved_or_non_public("allowed.pitchai.net"), message="public name rejected")

    @staticmethod
    def test_monitoring_access_uses_route_specific_credentials() -> None:
        """Dashboard identity cannot authorize the machine API or vice versa."""
        context = _context()
        access = RegistryAccess(context)
        identity = [(context.settings.dashboard_identity_header.encode(), b"fixture@pitchai.net")]
        access.require_monitoring_access(_request("/dashboard/api/v1/monitoring/summary", identity))
        with pytest.raises(HTTPException, match="monitoring bearer token required"):
            access.require_monitoring_access(_request("/api/v1/monitoring/summary", identity))
        with pytest.raises(HTTPException, match="PitchAI Entra SSO identity required"):
            access.require_monitoring_access(_request("/dashboard/api/v1/monitoring/summary", []))
        credential = secrets.token_urlsafe()
        context.app.state.settings = replace(context.settings, monitor_token=credential)
        bearer = [(b"authorization", f"Bearer {credential}".encode())]
        access.require_monitoring_access(_request("/api/v1/monitoring/summary", bearer))
        with pytest.raises(HTTPException, match="PitchAI Entra SSO identity required"):
            access.require_monitoring_access(_request("/dashboard/api/v1/monitoring/summary", bearer))

    @staticmethod
    async def test_missing_cookie_skips_database_and_errors_propagate() -> None:
        """Empty cookies short circuit; lookup failures do not become authenticated."""
        access = RegistryAccess(_context())
        with patch.object(dbm, "get_api_key_by_hash", side_effect=RuntimeError("isolated-lookup")):
            require(condition=await access.ui_get_auth(_request("/ui/tests", [])) is None,
                    message="empty cookie reached database")
            with pytest.raises(HTTPException, match="ui_not_authenticated"):
                await access.ui_require_auth(_request("/ui/tests", []))
            with pytest.raises(RuntimeError, match="isolated-lookup"):
                await access.ui_get_auth(_request("/ui/tests", [(b"cookie", b"e2e_token_hash=fixture")]))

    @staticmethod
    async def test_cache_reuses_identity_then_invalidates_at_exact_ttl() -> None:
        """Both file versions and the original cache age determine reuse."""
        context = _context()
        snapshot = md.MonitorData({}, {}, "synthetic-state", "synthetic-config", _NOW, None)
        cache: MonitorCache = {"loaded_at_ts": _NOW, "state_mtime": 1.0, "config_mtime": 1.0, "data": snapshot}
        context.app.state.monitor_cache = cache
        with patch("e2e_registry.app_context.file_mtime", return_value=1.0):
            with patch("e2e_registry.app_context.time.time", return_value=_NOW + 4.999):
                require(condition=await context.monitor_data() is snapshot, message="fresh cache identity changed")
            with (
                patch("e2e_registry.app_context.time.time", return_value=_NOW + 5),
                patch.object(md, "load_monitor_data", side_effect=RuntimeError("isolated-load")),
                pytest.raises(RuntimeError, match="isolated-load"),
            ):
                await context.monitor_data()
        require(condition=cache["data"] is snapshot and cache["loaded_at_ts"] == _NOW,
                message="failed load renewed or discarded snapshot")

    @staticmethod
    async def test_invalid_cache_rebuild_and_metadata_unavailability() -> None:
        """A replacement cache is initialized, and absent mtimes keep their sentinel."""
        context = _context()
        context.app.state.monitor_cache = []
        snapshot = md.MonitorData({}, {}, "synthetic-state", "synthetic-config", _NOW, "fixture-unavailable")
        with (
            patch("e2e_registry.app_context.file_mtime", return_value=None),
            patch("e2e_registry.app_context.time.time", return_value=_NOW),
            patch.object(md, "load_monitor_data", return_value=snapshot),
        ):
            require(condition=await context.monitor_data() is snapshot, message="loaded evidence altered")
        # The awaited loader replaces the deliberately invalid list in State;
        # invalidate the checker's earlier assignment narrowing at this read.
        cache = cast("MonitorCache", cast("object", context.app.state.monitor_cache))
        require(condition=cache == {"data": snapshot, "loaded_at_ts": _NOW, "state_mtime": None, "config_mtime": None},
                message="cache fields changed")
        require(condition=file_mtime("") is None, message="empty filename became current directory")

    @staticmethod
    def test_quarantine_keeps_write_order_and_does_not_hide_failure() -> None:
        """Only disallowed named records reach writes; an error stops later writes."""
        policy = RegistryHostPolicy(_context())
        summary = {"tests": [
            {"tenant_id": "t", "test_id": "one", "base_url": "https://example.com"},
            {"tenant_id": "t", "test_id": "safe", "base_url": "https://allowed.pitchai.net"},
            {"tenant_id": "", "test_id": "missing", "base_url": "https://example.com"},
            {"tenant_id": "t", "test_id": "two", "base_url": "https://example.com"},
        ]}
        with patch.object(dbm, "status_summary", return_value=summary):
            with patch.object(dbm, "set_test_disabled", side_effect=[True, False]) as write:
                require(condition=policy.quarantine_disallowed_tests() == 1, message="write outcome count changed")
                require(condition=write.call_count == _EXPECTED_QUARANTINE_WRITES,
                        message="extra or missing quarantine write")
            with patch.object(dbm, "set_test_disabled", side_effect=RuntimeError("isolated-write")) as write:
                with pytest.raises(RuntimeError, match="isolated-write"):
                    policy.quarantine_disallowed_tests()
                require(condition=write.call_count == 1, message="quarantine continued after failed write")
