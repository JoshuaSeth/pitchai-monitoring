# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated real-ASGI administration, tenant reads and retained artifact contracts."""

from __future__ import annotations

import asyncio
import secrets
import tempfile
import unittest
from dataclasses import replace
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

import pytest

from domain_checks.dft_test_support import require

from . import auth
from . import db as dbm
from .app import create_app
from .asgi_test_support import request
from .settings import RegistrySettings

if TYPE_CHECKING:
    from .dashboard_records import Record

_TENANT = dbm.AuthedTenant("fixture-tenant", "fixture-key")
_HEADERS = {"authorization": "Bearer fixture-tenant", "content-type": "application/json"}
_TENANT_TEST_COUNT = 3


def _settings() -> RegistrySettings:
    return RegistrySettings(
        admin_token=secrets.token_urlsafe(), monitor_token=secrets.token_urlsafe(), runner_token="",
        alerts_enabled=False, dispatch_enabled=False, strict_base_url_policy=False,
    )


class RegistryReadAdminTests(unittest.IsolatedAsyncioTestCase):
    """No lifespan, real database, outgoing socket, browser or receiver."""

    @staticmethod
    async def test_admin_dependency_and_body_errors_precede_database() -> None:
        """Admission, missing body and Pydantic errors preserve status and no write."""
        settings = _settings()
        application = create_app(settings)
        path = "/api/v1/admin/tenants"
        headers = {"authorization": f"Bearer {settings.admin_token}", "content-type": "application/json"}
        with patch.object(dbm, "create_tenant", side_effect=AssertionError("unexpected write")) as write:
            response = await request(application, path, method="POST")
            require(condition=response.status_code == HTTPStatus.UNAUTHORIZED, message="missing auth admitted")
            response = await request(application, path, method="POST", headers=headers)
            require(condition=response.status_code == HTTPStatus.BAD_REQUEST and
                    response.json()["detail"] == "missing_body", message="missing-body response changed")
            response = await request(application, path, method="POST", headers=headers, body=b'{"name":""}')
            require(condition=response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY,
                    message="Pydantic request constraint lost")
            require(condition=write.call_count == 0, message="invalid request reached write")

    @staticmethod
    async def test_admin_key_keeps_token_hash_and_record_envelope() -> None:
        """The returned token and persisted hash describe the same new key."""
        settings = _settings()
        application = create_app(settings)
        headers = {"authorization": f"Bearer {settings.admin_token}", "content-type": "application/json"}
        with patch.object(dbm, "create_api_key", return_value={"id": "new-key"}) as write:
            response = await request(application, "/api/v1/admin/api_keys", method="POST", headers=headers,
                                     body=b'{"tenant_id":"fixture-tenant","name":"fixture"}')
            require(condition=response.status_code == HTTPStatus.OK, message="key creation response failed")
            result = response.json()
            require(condition=result["api_key"] == {"id": "new-key"}, message="key envelope changed")
            values = cast("Record", write.call_args.kwargs)
            require(condition=values == {"tenant_id": _TENANT.tenant_id, "name": "fixture",
                                         "token_hash": auth.hash_token(str(result["token"]))},
                    message="stored key hash or scope changed")

    @staticmethod
    async def test_run_reads_keep_tenant_scope_limit_and_missing_response() -> None:
        """Authenticated read arguments and not-found details remain stable."""
        application = create_app(_settings())
        with (
            patch.object(auth, "get_api_key_by_hash", return_value=_TENANT),
            patch.object(dbm, "list_runs", return_value=[{"id": "run"}]) as listing,
            patch.object(dbm, "get_run", return_value=None) as lookup,
        ):
            response = await request(application, "/api/v1/tests/fixture-test/runs?limit=7", headers=_HEADERS)
            require(condition=response.json() == {"ok": True, "runs": [{"id": "run"}]}, message="run list changed")
            require(condition=cast("Record", listing.call_args.kwargs) ==
                    {"tenant_id": _TENANT.tenant_id, "test_id": "fixture-test", "limit": 7},
                    message="run list scope changed")
            response = await request(application, "/api/v1/runs/missing", headers=_HEADERS)
            require(condition=response.status_code == HTTPStatus.NOT_FOUND and
                    response.json()["detail"] == "not_found", message="run missing response changed")
            require(condition=cast("Record", lookup.call_args.kwargs) ==
                    {"tenant_id": _TENANT.tenant_id, "run_id": "missing"}, message="run lookup scope changed")

    @staticmethod
    async def test_global_and_tenant_status_remain_separate() -> None:
        """Admin/monitor credentials bypass tenant filtering, with no tenant lookup."""
        settings = _settings()
        application = create_app(settings)
        summary: Record = {"tests": [
            {"tenant_id": _TENANT.tenant_id, "effective_ok": 0},
            {"tenant_id": _TENANT.tenant_id, "effective_ok": "bad"},
            {"tenant_id": _TENANT.tenant_id, "effective_ok": None},
            {"tenant_id": "foreign", "effective_ok": 0},
        ], "retained": "global"}
        with (
            patch.object(dbm, "status_summary", return_value=summary),
            patch.object(auth, "get_api_key_by_hash", return_value=_TENANT) as lookup,
        ):
            for token in (settings.admin_token, settings.monitor_token):
                response = await request(application, "/api/v1/status/summary",
                                         headers={"authorization": f"Bearer {token}"})
                require(condition=response.json() == summary, message="global response was filtered")
            require(condition=lookup.call_count == 0, message="global credential reached tenant lookup")
            response = await request(application, "/api/v1/status/summary", headers=_HEADERS)
            result = response.json()
            require(condition=result["total_tests"] == _TENANT_TEST_COUNT and result["failing_tests"] == 1,
                    message="tenant summary classification changed")
            require(condition="retained" not in result, message="global-only field leaked into tenant summary")

    @staticmethod
    async def test_auth_failure_and_database_cancellation_do_not_report_success() -> None:
        """Invalid tenant admission skips observation; cancellation escapes the route."""
        application = create_app(_settings())
        with (
            patch.object(auth, "get_api_key_by_hash", return_value=None),
            patch.object(dbm, "status_summary", side_effect=AssertionError("observation reached")) as read,
        ):
            response = await request(application, "/api/v1/status/summary", headers=_HEADERS)
            require(condition=response.status_code == HTTPStatus.UNAUTHORIZED and
                    response.json()["detail"] == "unauthorized", message="tenant refusal changed")
            require(condition=read.call_count == 0, message="failed admission reached observation")
        with (
            patch.object(auth, "get_api_key_by_hash", return_value=_TENANT),
            patch("e2e_registry.app_read_routes.asyncio.to_thread", side_effect=asyncio.CancelledError("fixture")),
            pytest.raises(asyncio.CancelledError, match="fixture"),
        ):
            await request(application, "/api/v1/status/summary", headers=_HEADERS)

    @staticmethod
    async def test_artifact_bytes_and_resolved_path_refusals() -> None:
        """Only an existing scoped file is served; this temporary tree is removed."""
        with tempfile.TemporaryDirectory(prefix="registry-artifact-contract-") as directory:
            path = Path(directory) / _TENANT.tenant_id / "test" / "run" / "proof.json"
            path.parent.mkdir(parents=True)
            path.write_bytes(b'{"fixture":true}')
            application = create_app(replace(_settings(), artifacts_dir=directory))
            with (
                patch.object(auth, "get_api_key_by_hash", return_value=_TENANT),
                patch.object(dbm, "get_run", return_value={"test_id": "test"}) as lookup,
            ):
                response = await request(application, "/api/v1/runs/run/artifacts/proof.json", headers=_HEADERS)
                require(condition=response.status_code == HTTPStatus.OK and response.json() == {"fixture": True},
                        message="artifact bytes changed")
                lookup.return_value = {"test_id": str(Path(directory).parent)}
                response = await request(application, "/api/v1/runs/run/artifacts/proof.json", headers=_HEADERS)
                require(condition=response.status_code == HTTPStatus.BAD_REQUEST and
                        response.json()["detail"] == "invalid_artifact_path", message="resolved escape admitted")
                lookup.return_value = {}
                response = await request(application, "/api/v1/runs/run/artifacts/proof.json", headers=_HEADERS)
                require(condition=response.json()["detail"] == "run_not_found", message="empty run response changed")

    @staticmethod
    async def test_app_instances_and_replaced_settings_keep_request_ownership() -> None:
        """Shared route definitions do not retain another application's settings."""
        settings = _settings()
        first, second = create_app(settings), create_app(replace(settings, db_path="other-fixture"))
        first.state.settings = replace(settings, db_path="replaced-fixture")
        observed: list[str] = []

        def status(received: RegistrySettings) -> Record:
            observed.append(received.db_path)
            return {"ok": True}

        with patch.object(dbm, "status_summary", side_effect=status):
            for application in (first, second):
                response = await request(application, "/api/v1/status/summary",
                                         headers={"authorization": f"Bearer {settings.admin_token}"})
                require(condition=response.json() == {"ok": True}, message="status response failed")
        require(condition=observed == ["replaced-fixture", "other-fixture"], message="application settings captured")
